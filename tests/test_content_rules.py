"""Chạy: python -m unittest discover -s tests"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot_truc_nhom as bot
import content_pipeline as cp
import content_queue
import validators as v

SOURCE = "Most traders risk too much on each trade and lose 2 percent of the account every single time they ignore the stop."
QUOTE = "risk too much on each trade and lose 2 percent"
URL = "https://www.youtube.com/watch?v=abc"


def video(**over):
    item = {
        "id": "video_abc", "kind": "video_review", "title": "Tác giả: Quản lý rủi ro", "author": "Tác giả", "platform": "YouTube",
        "transcript_kind": "auto", "topic": "quan_tri_rui_ro", "source_url": URL,
        "text": f"REVIEW VIDEO. Tóm tắt do AI từ phụ đề.\nChủ đề: quản lý rủi ro\nNguồn: {URL}\nBạn đã thử chưa?",
        "facts": [{"text": "x", "quote": QUOTE}], "claims_text": [], "generated_text": "Người mới mất 2 phần trăm mỗi lần.",
        "source_text": SOURCE, "code_numbers": [],
    }
    item.update(over)
    return item


class CheckItem(unittest.TestCase):
    def test_good_review_passes(self):
        self.assertEqual(v.check_item(video()), [])

    def test_pip_hook_rejected(self):
        for title in ("Lệnh đang lãi 15 pip thì sao", "Kiếm $30/ngày từ vàng", "Lãi 2% mỗi ngày"):
            self.assertIn("hook_pip_or_income", v.check_item(video(title=title)), title)

    def test_old_scenario_post_rejected(self):
        self.assertIn("hook_pip_or_income", v.check_item(video(text=f"Lệnh vàng đang lãi 17 pip AI {URL}")))

    def test_commitment_and_fundraising_rejected(self):
        for phrase in ("cam kết lợi nhuận mỗi tháng", "kêu gọi vốn đầu tư", "nhận ủy thác cho bạn", "lãi chắc không rủi ro"):
            errs = v.check_item(video(text=video()["text"] + "\n" + phrase))
            self.assertIn("profit_commitment_or_fundraising", errs, phrase)

    def test_third_party_claim_is_allowed_only_when_marked(self):
        claim = "Tác giả nói có cách lãi chắc"
        text = video()["text"] + "\n- Tuyên bố (chưa kiểm chứng): " + claim
        self.assertIn("profit_commitment_or_fundraising", v.check_item(video(text=text)))
        self.assertEqual(v.check_item(video(text=text, claims_text=[claim])), [])

    def test_call_to_trade_rejected(self):
        self.assertIn("call_to_trade", v.check_item(video(text=video()["text"] + "\nBạn nên mua vàng lúc này")))

    def test_slop_rejected(self):
        self.assertIn("slop_phrase", v.check_item(video(text=video()["text"] + "\nCác sếp thấy sao?")))

    def test_invented_number_rejected(self):
        errs = v.check_item(video(generated_text="Tỷ lệ thắng 87 phần trăm"))
        self.assertTrue(any(e.startswith("number_not_in_source") for e in errs))

    def test_fake_quote_rejected(self):
        self.assertIn("quote_not_in_source", v.check_item(video(facts=[{"text": "x", "quote": "this sentence was never spoken by anyone"}])))

    def test_no_transcript_rejected(self):
        self.assertIn("no_transcript", v.check_item(video(transcript_kind="none")))

    def test_requires_ai_label_and_link(self):
        errs = v.check_item(video(text="Một bài không nhãn"))
        self.assertIn("missing_ai_label", errs)
        self.assertIn("missing_source_link", errs)

    def test_referral_link_rejected(self):
        self.assertIn("referral_link", v.check_item(video(text=video()["text"] + "\nhttps://broker.com/?ref=123")))

    def test_every_bank_poll_passes(self):
        for entry in cp.POLL_BANK:
            self.assertEqual(v.check_item(cp.build_poll(entry)), [], entry["id"])

    def test_poll_about_pips_rejected(self):
        item = cp.build_poll({"id": "x", "group": "ky_luat", "q": "Hôm nay bạn ăn được bao nhiêu pip?", "o": ["Ít", "Nhiều"]})
        self.assertIn("poll_pip_or_income", v.check_item(item))

    def test_word_number_in_english_source_allowed(self):
        src = "Most traders risk too much on each trade and lose two percent of the account within fifteen minutes."
        item = video(source_text=src, facts=[{"text": "x", "quote": "risk too much on each trade and lose two percent"}],
                     generated_text="Người mới mất 2% chỉ trong 15 phút.")
        self.assertEqual(v.check_item(item), [])

    def test_punctuation_in_quote_allowed(self):
        item = video(facts=[{"text": "x", "quote": "risk too much, on each trade, and lose 2 percent..."}])
        self.assertEqual(v.check_item(item), [])

    def test_mr_pips_case_title_allowed(self):
        item = video(kind="case_study", title="Hồ sơ rủi ro: Mr. Pips",
                     text=f"[Hồ sơ rủi ro: Mr. Pips] Vụ việc lớn.\nNguồn (AI): {URL}")
        self.assertEqual(v.check_item(item), [])

    def test_low_quality_score_rejected(self):
        errs = v.check_item(video(quality_score=5))
        self.assertTrue(any(e.startswith("low_quality_score") for e in errs))


class Schedule(unittest.TestCase):
    now = 2_000_000_000

    def test_same_scenario_text_is_too_similar(self):
        text = "Lệnh vàng đang chạy tốt thì còn đúng mười phút nữa ra tin lãi suất Fed bạn xử lý thế nào"
        hist = [{"kind": "thread_review", "text": text, "ts": self.now - 86400}]
        self.assertIn("too_similar", v.check_schedule({"kind": "case_study", "text": text}, hist, self.now))

    def test_debate_weekly_cap(self):
        hist = [{"kind": "debate", "ts": self.now - 86400}, {"kind": "video_review", "ts": self.now - 3600}]
        self.assertIn("debate_weekly_cap", v.check_schedule({"kind": "debate", "text": "khác hẳn"}, hist, self.now))

    def test_poll_rotation(self):
        hist = [{"kind": "poll", "group": "rui_ro", "ts": self.now - 10 * 86400}]
        self.assertIn("poll_group_twice", v.check_schedule({"kind": "poll", "group": "rui_ro", "poll": {"question": "q"}}, hist, self.now))

    def test_author_cooldown(self):
        hist = [{"kind": "video_review", "author": "A", "ts": self.now - 86400}]
        self.assertIn("author_cooldown", v.check_schedule({"kind": "video_review", "author": "A", "text": "z"}, hist, self.now))


class BotBehaviour(unittest.TestCase):
    def test_welcome_has_no_user_id(self):
        sent = {}
        with mock.patch.object(bot, "api_call", side_effect=lambda m, p=None: sent.update(p or {}) or {"ok": True, "result": {"message_id": 1}}):
            bot.welcome_new_members([{"id": 987654321, "first_name": "An", "username": "an123"}], {})
        visible = sent["text"].replace("tg://user?id=987654321", "")
        self.assertNotIn("987654321", visible)
        self.assertNotIn("an123", visible)

    def test_chart_link_allowed_referral_blocked(self):
        self.assertFalse(bot.detect_violation({"text": "chart của mình https://www.tradingview.com/x/abc/"})[0])
        self.assertTrue(bot.detect_violation({"text": "vào đây https://t.me/nhomkhac"})[0])
        self.assertTrue(bot.detect_violation({"text": "https://broker.com/?ref=1"})[0])

    def test_competitor_name_allowed_scam_blocked(self):
        self.assertFalse(bot.detect_violation({"text": "Exness với VT khác nhau thế nào?"})[0])
        self.assertTrue(bot.detect_violation({"text": "bên mình cam kết lợi nhuận 10%"})[0])

    def test_first_strike_no_mute_second_strike_timed_mute(self):
        calls = []
        msg = {"chat": {"id": bot.DISCUSSION_CHAT_ID}, "message_id": 5, "from": {"id": 7, "first_name": "A"}, "text": "x"}
        state = {}
        with mock.patch.object(bot, "api_call", side_effect=lambda m, p=None: calls.append((m, p)) or {"ok": True}):
            bot.handle_violation(msg, "lý do", state)
            self.assertFalse([c for c in calls if c[0] == "restrictChatMember"])
            bot.handle_violation(msg, "lý do", state)
        restrict = [c for c in calls if c[0] == "restrictChatMember"]
        self.assertEqual(len(restrict), 1)
        self.assertIn("until_date", restrict[0][1])

    def test_rut_rau_is_not_a_lead(self):
        with mock.patch.object(bot, "send_text") as send:
            bot.notify_explicit_lead({"text": "Rút râu H1 là gì?", "message_id": 1})
            send.assert_not_called()
            bot.notify_explicit_lead({"text": "Mình muốn mở tài khoản", "message_id": 2})
            send.assert_called_once()

    def test_answers(self):
        self.assertEqual(bot.answer_text("Giờ có nên mua vàng không", []), (bot.ADVICE_REPLY, False))
        self.assertEqual(bot.answer_text("Mình bị cháy tài khoản rồi", []), (bot.CRISIS_REPLY, True))
        self.assertEqual(bot.answer_text("spread là gì", []), (bot.NO_ANSWER_REPLY, False))

    def test_lot_calc(self):
        self.assertIn("0.02 lot", bot.calc_lot(["1000", "1", "5"]))
        with self.assertRaises(ValueError):
            bot.calc_lot(["0", "1", "5"])

    def test_poll_result_small_sample(self):
        out = bot.format_poll_result({"total_voter_count": 2, "options": [{"text": "A", "voter_count": 2}]})
        self.assertIn("Quá ít phiếu", out)

    def test_stats_counts_fast_leavers(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bot, "METRICS_FILE", os.path.join(d, "m.json")), \
                mock.patch.object(content_queue, "QUEUE_DIR", os.path.join(d, "q")), mock.patch.object(content_queue, "STATE_FILE", os.path.join(d, "s.json")):
            base = {"chat": {"id": bot.DISCUSSION_CHAT_ID}, "new_chat_member": {"user": {"id": 1}, "status": "member"}, "old_chat_member": {"status": "left"}}
            bot.record_member_update(base)
            bot.record_member_update({**base, "new_chat_member": {"user": {"id": 1}, "status": "left"}, "old_chat_member": {"status": "member"}})
            out = bot.stats_text()
        self.assertIn("Vào: 1", out)
        self.assertIn("Rời trong 24 giờ sau khi vào: 1", out)


class AutoSetup(unittest.TestCase):
    def run_setup(self, status, state):
        calls = []

        def api(method, payload=None):
            calls.append(method)
            if method == "getChatMember":
                return {"ok": True, "result": {"status": status, "can_pin_messages": True, "can_restrict_members": True}}
            return {"ok": True, "result": {"message_id": 9}}
        with mock.patch.object(bot, "api_call", side_effect=api), mock.patch.object(bot, "save_state"):
            bot.ensure_setup(state)
        return calls

    def test_pins_only_once(self):
        state = {}
        self.assertIn("pinChatMessage", self.run_setup("administrator", state))
        self.assertTrue(state["intro_pinned"])
        self.assertNotIn("pinChatMessage", self.run_setup("administrator", state))

    def test_not_admin_alerts_once_and_does_not_pin(self):
        state = {}
        first = self.run_setup("member", state)
        self.assertNotIn("pinChatMessage", first)
        self.assertIn("sendMessage", first)
        self.assertNotIn("sendMessage", self.run_setup("member", state))

    def test_weekly_report_once_on_monday(self):
        monday = time.mktime((2026, 11, 2, 9, 30, 0, 0, 0, -1))
        state = {}
        with mock.patch.object(bot, "send_text", return_value={"ok": True}) as send, mock.patch.object(bot, "save_state"),                 mock.patch.object(bot, "stats_text", return_value="x"):
            self.assertFalse(bot.send_weekly_report(state, monday - 86400))
            self.assertTrue(bot.send_weekly_report(state, monday))
            self.assertFalse(bot.send_weekly_report(state, monday + 3600))
        send.assert_called_once()


class QueueFlow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(content_queue, "QUEUE_DIR", os.path.join(self.dir.name, "q")),
                        mock.patch.object(content_queue, "STATE_FILE", os.path.join(self.dir.name, "s.json")),
                        mock.patch.object(bot, "sync_git_state")]
        for p in self.patches:
            p.start()
        self.calls = []
        self.api = mock.patch.object(bot, "api_call", side_effect=self._api)
        self.api.start()
        self.t = time.mktime((2026, 11, 2, 8, 30, 0, 0, 0, -1))

    def tearDown(self):
        self.api.stop()
        for p in self.patches:
            p.stop()
        self.dir.cleanup()

    def _api(self, method, payload=None):
        self.calls.append((method, payload))
        if method == "stopPoll":
            return {"ok": True, "result": {"total_voter_count": 6, "options": [{"text": "A", "voter_count": 4}, {"text": "B", "voter_count": 2}]}}
        return {"ok": True, "result": {"message_id": len(self.calls)}}

    def group_posts(self):
        return [c for c in self.calls if c[0] in ("sendMessage", "sendPoll") and c[1]["chat_id"] == bot.DISCUSSION_CHAT_ID]

    def test_empty_queue_is_silent(self):
        for offset in range(0, 86400, 900):
            self.assertFalse(bot.process_queue({}, self.t + offset))
        self.assertEqual(self.calls, [])

    def test_preview_then_publish(self):
        content_queue.add_item(video())
        bot.process_queue({}, self.t)
        self.assertEqual(self.group_posts(), [])
        self.assertTrue(any(c[1]["chat_id"] == bot.INTERNAL_CHAT_ID for c in self.calls))
        bot.process_queue({}, self.t + 1800)
        self.assertEqual(self.group_posts(), [])
        self.assertTrue(bot.process_queue({}, self.t + 3700))
        self.assertEqual(len(self.group_posts()), 1)

    def test_blocked_item_never_posts(self):
        content_queue.add_item(video())
        bot.process_queue({}, self.t)
        bot.handle_callback({"id": "1", "data": "block:video_abc", "message": {"chat": {"id": bot.INTERNAL_CHAT_ID}}}, {"user_ids": set(), "usernames": set()})
        bot.process_queue({}, self.t + 3700)
        self.assertEqual(self.group_posts(), [])

    def test_paused_bot_does_nothing(self):
        content_queue.add_item(video())
        bot.process_queue({"paused": True}, self.t)
        self.assertEqual(self.calls, [])

    def test_bad_item_in_queue_is_not_posted(self):
        content_queue.add_item(video(title="Đang lãi 20 pip"))
        bot.process_queue({}, self.t)
        bot.process_queue({}, self.t + 3700)
        self.assertEqual(self.group_posts(), [])

    def test_debate_posts_poll_and_real_result(self):
        item = video(id="thread_1", kind="debate", author="r/Forex", poll={"question": "Nên chốt một phần hay giữ hết?", "options": ["A", "B"]})
        content_queue.add_item(item)
        bot.process_queue({}, self.t)
        bot.process_queue({}, self.t + 3700)
        self.assertEqual([c[0] for c in self.group_posts()], ["sendMessage", "sendPoll"])
        bot.check_debate_results(self.t + 3700 + 3600)
        self.assertFalse([c for c in self.calls if c[0] == "stopPoll"])
        bot.check_debate_results(self.t + 3700 + bot.DEBATE_RESULT_AFTER + 1)
        self.assertEqual(len([c for c in self.calls if c[0] == "stopPoll"]), 1)
        self.assertIn("tổng 6 phiếu", self.group_posts()[-1][1]["text"])

    def test_max_two_posts_a_day_and_gap(self):
        for i in range(4):
            content_queue.add_item(video(id=f"video_{i}", author=f"A{i}", title=f"Tác giả {i}: chủ đề {i}", topic=f"t{i}",
                                         text=f"REVIEW VIDEO AI {URL} " + " ".join(f"tu{i}x{n}" for n in range(40))))
        posted = 0
        for offset in range(0, 86400, 300):
            posted += 1 if bot.process_queue({}, self.t + offset) else 0
        self.assertEqual(posted, 2)


class PipelineBuild(unittest.TestCase):
    def test_llm_no_key_makes_no_item(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            self.assertIsNone(cp.ask_json("x"))

    def test_video_review_from_real_quotes(self):
        segs = [{"text": SOURCE + " " + "padding words about discipline and journaling " * 40, "start": 75.0}]
        src = segs[0]["text"]
        llm = {"relevant": True, "topic": "quan_tri_rui_ro", "summary": "Bàn về rủi ro mỗi lệnh",
               "points": [{"text": "Người mới rủi ro quá nhiều", "quote": QUOTE},
                          {"text": "Bỏ qua điểm dừng làm mất 2 phần trăm", "quote": "every single time they ignore the stop"},
                          {"text": "Ý bịa", "quote": "never said anywhere in this video at all"}],
               "claims": [{"claim": "Đa số rủi ro quá mức", "quote": "Most traders risk too much on each trade", "evidence": "không đưa bằng chứng"}],
               "fits": "Người mới", "not_fits": "Người đã có quy tắc", "weakness": "Không có cỡ mẫu",
               "author_interest": "không thấy trong phụ đề", "question": "Bạn đặt rủi ro mỗi lệnh thế nào?"}
        with mock.patch.object(cp, "ask_json", return_value=llm):
            item = cp.build_video_review({"video_id": "abc", "title": "Risk", "author": "Tác giả"}, segs, "auto")
        self.assertEqual(v.check_item(item), [])
        self.assertNotIn("Ý bịa", item["text"])
        self.assertIn("phút 01:15", item["text"])
        self.assertIn(src[:20], item["source_text"])

    def test_invented_number_in_review_blocked(self):
        segs = [{"text": SOURCE + " padding " * 300, "start": 0.0}]
        llm = {"relevant": True, "summary": "Chiến lược thắng 87 phần trăm", "points": [
            {"text": "a", "quote": QUOTE}, {"text": "b", "quote": "every single time they ignore the stop"}],
            "claims": [{"claim": "c", "quote": "Most traders risk too much on each trade", "evidence": "không"}],
            "fits": "x", "not_fits": "y", "weakness": "z", "author_interest": "z", "question": "Bạn thấy sao?"}
        with mock.patch.object(cp, "ask_json", return_value=llm):
            item = cp.build_video_review({"video_id": "abc", "title": "Risk", "author": "T"}, segs, "auto")
        self.assertTrue(any(e.startswith("number_not_in_source") for e in v.check_item(item)))

    def test_timestamp_spans_short_caption_segments(self):
        segs = [{"text": "intro words here", "start": 3.0}, {"text": "Most traders risk", "start": 65.0}, {"text": "too much on each trade", "start": 67.0}]
        self.assertEqual(cp._timestamp("Most traders risk too much on each trade", segs), "01:05")
        self.assertEqual(cp._timestamp("not in the captions", segs), "")

    def test_no_transcript_no_item(self):
        self.assertIsNone(cp.build_video_review({"video_id": "a", "title": "t", "author": "x"}, [{"text": "ngắn", "start": 0}], "auto"))


if __name__ == "__main__":
    unittest.main()
