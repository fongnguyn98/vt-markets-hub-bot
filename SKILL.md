---
name: vt-community-radar
description: Quy trình tự động quét 4 Sheet nguồn Quốc tế (Website, YouTube, TikTok, Reddit) từ Google Sheets Online của hệ thống VT Markets Hub, giải mã tin tức kết hợp chỉ báo định lượng TradingView-TA, tự động chụp biểu đồ nến XAU/USD thời gian thực (mplfinance), cân bằng 5 nhóm nội dung và tự động đăng lên nhóm Thảo Luận. Bot chạy 100% trên GitHub Actions (repo fongnguyn98/vt-markets-hub-bot), KHÔNG chạy trên máy local.
---

# VT Community Radar & Content Balancing Skill (chạy 100% trên GitHub Actions)

> [!IMPORTANT]
> **BOT CHẠY 100% TRÊN GITHUB ACTIONS — KHÔNG CHẠY THƯ MỤC LOCAL.**
> Nguồn chuẩn duy nhất là repo `https://github.com/fongnguyn98/vt-markets-hub-bot` (workflow `.github/workflows/vt_bot_247.yml`).
> Tuyệt đối không chạy `bot_truc_nhom.py` / `watchdog_bot.py` trên máy (gây `409 Conflict`, đăng trùng bài). Thư mục D: không còn dùng để chạy.

## 1. Nguyên Tắc Vận Hành Cốt Lõi (Strict Rules)
1. **100% Nguồn Quốc Tế Trên Google Sheets Online:**
   - Link: `https://docs.google.com/spreadsheets/d/1-HgPzrchtbVtyskdawDfx5Hum4eaJK-8COgJ2Ytdoik/edit?usp=sharing`
   - 4 Tab: `Website` (56 trang tin quốc tế), `YouTube` (70 kênh KOL quốc tế), `TikTok` (35 kênh KOL/News quốc tế), `Reddit` (20 cộng đồng quốc tế).
2. **100% Tiếng Việt Đời Thường, Đan Xen Bài Dài (Có Icon Đầu Đoạn) & Tin Nhắn Ngắn (Không Icon) Theo 5 Insight Cốt Lõi:**
   - **Bài chia sẻ dài (2–3 đoạn cách nhau bằng `\n\n`):** Mỗi đoạn có **1 icon điểm nhấn ở đầu đoạn** (`📌`, `💡`, `🎯`, `💰`, `👉`...) để bố cục rõ ràng, dễ đọc lướt.
   - **Tin nhắn ngắn đan xen trong khung giờ giao dịch (`10:15`, `16:00`, `20:45` & khi nhóm vắng):** Chỉ 1–2 câu ngắn gọn, **hoàn toàn KHÔNG dùng icon**, tự nhiên như một người anh em thật đang nhắn tin hỏi thăm/trao đổi trong nhóm.
   - **Văn phong & Xưng hô:** Gọi thành viên là **"các sếp"**, tôn trọng KOL quốc tế (*"TJR"*, *"chuyên gia Raja Banks"*, *"Umar Ashraf"*, *"Brad Goh"*, *"Smart Risk"*).
   - **Bám sát 5 Insight cốt lõi của người mới & trader bận rộn:**
     1. **Quá tải thông tin, không biết bắt đầu từ đâu:** Lộ trình tối giản (chỉ cần 1 cặp `XAU/USD` + 1 khung giờ + 1 thế nến rút râu hoặc tờ giấy nhớ 3 gạch đầu dòng).
     2. **Bận đi làm hành chính / kinh doanh, không có thời gian canh bảng điện:** Cách giao dịch nhàn đầu chỉ cần 45–60 phút cố định mỗi ngày (đầu phiên Âu `14h00` hoặc phiên Mỹ `20h15`).
     3. **Bài toán lợi nhuận thực tế & thu nhập phụ đều đặn:** Cách kiếm đều `$25 – $45/ngày` (~700k – 1,1 triệu VNĐ) từ 20–30 pips Vàng trên vốn `$500 – $1,000`.
     4. **Tâm lý chốt lãi non nhưng gồng lỗ sâu & FOMO:** Cách cài sẵn SL/TP và dời SL về hòa vốn để giữ trọn lợi nhuận.
     5. **Tối ưu lợi nhuận ròng & rút tiền thật về túi:** Quy tắc rút 50% lãi hàng tuần về ngân hàng + cộng dồn hoàn phí tự động `Backcom 100%` & tài khoản `Raw ECN`.
3. **Nguyên Tắc Pháp Lý Bất Di Bất Dịch — Trích Dẫn Khách Quan Từ Nguồn Thứ 3 (Tuyệt Đối Không Nhận Định Chủ Quan):**
   - **Công thức bắt buộc cho mọi bài đăng & câu trả lời của Bot:** *"Theo chia sẻ của [Chuyên gia A / Kênh B / Cộng đồng C] về [Chiến lược / Góc nhìn D]..."*
   - Bot và VT Markets **tuyệt đối không tự đưa ra dự đoán thị trường chủ quan**, không khuyên Mua/Bán, không dùng các cụm từ mang tính cá nhân của Bot như *"Mình nghĩ Vàng sẽ lên/xuống..."*, *"Đoạn này các sếp nên Buy/Sell ở..."*. Mọi nhận định xu hướng, mốc giá hay phương pháp đều phải gắn rõ tên nguồn phát ngôn (ví dụ: *FXEmpire, CNBC, Investing, Raja Banks, TJR, Brad Goh, Smart Risk, Umar Ashraf, diễn đàn r/Gold, bảng thống kê tự động TradingView*) để trách nhiệm thông tin hoàn toàn thuộc về nguồn tin quốc tế.
   - **Ưu tiên số 1 cho mục Tin tức (`fetch_youtube_kol_news_forecasts`):** Tự động tìm các video nhận định & Podcast mới nhất trên YouTube của các KOL/Chuyên gia quốc tế phân tích về Vàng (`XAU/USD`), Dầu mỏ (`WTI`), USD (`DXY`) $\rightarrow$ Dùng `YouTubeTranscriptApi` bóc trực tiếp lời nhận định của chuyên gia $\rightarrow$ Dịch mượt sang tiếng Việt theo cấu trúc trích dẫn khách quan + Thumbnail gốc + Link YouTube gốc.
4. **Cơ Chế Tiếp Chuyện Tư Duy Linh Hoạt & Phân Loại 3 Cấp Độ Người Hỏi (`classify_user_level` + `generate_smart_trader_reply`):**
   - Khi thành viên tag `@vtmarkets8386_bot`, gọi chữ `"bot"`, hoặc Reply vào tin nhắn của Bot, hệ thống tự động phân loại người hỏi và tư duy linh hoạt theo đúng ngữ cảnh câu hỏi (luôn dẫn nguồn thứ 3 khách quan, không trả lời rập khuôn):
     - **Cấp độ 1 — `BEGINNER` (Người mới tinh / Chưa biết gì về trade):** Tuyệt đối KHÔNG dùng thuật ngữ hàn lâm (`RSI`, `EMA20`, `Bollinger`, `pip`, `lot`, `R:R`). Trả lời 100% bằng ngôn ngữ đời thường, ví dụ số tiền cụ thể (`$10 – $30`, `500k – 700k`), lời khuyên thực tế và dễ hiểu.
     - **Cấp độ 2 — `EXPERIENCED` (Trader đã có kinh nghiệm — dùng từ khóa `H1`, `M15`, `RSI`, `EMA`, `SL`, `lot`, `cản`, `thanh khoản`...):** Trả lời ngang hàng bằng thuật ngữ thực chiến kết hợp số liệu `TradingView-TA` thời gian thực.
     - **Cấp độ 3 — `BROKER_LEAD` (Khách hỏi về Sàn, Mở tài khoản, Nạp rút, Hoàn phí Backcom 100%, Raw ECN):** Giải đáp rõ ràng quyền lợi tại VT Markets và tự động bắn cảnh báo kèm nhãn phân loại trình độ về nhóm `[NỘI BỘ] Báo Khách & Sale`.
5. **Cơ Chế Ảnh Minh Họa Chuẩn Xác (Ảnh Gốc $\rightarrow$ Phương Án 1: Biểu Đồ Nến Thời Gian Thực $\rightarrow$ Phương Án 2: Ảnh Báo Chí):**
   - **Nếu nguồn có ảnh gốc / thumbnail gốc:** Lấy 100% ảnh bìa gốc bài báo (`enclosure` / `og:image`) hoặc Thumbnail gốc YouTube (`i.ytimg.com`) kèm link gốc.
   - **Nếu không có ảnh gốc (Ưu tiên Phương án 1):** Hàm `generate_live_xauusd_chart()` tự động dùng repo `mplfinance` vẽ và xuất ảnh **Biểu đồ Nến `XAU/USD` khung M15 thời gian thực** (giao diện Dark Mode chuẩn TradingView `#131722`, có sẵn `EMA 20`, `EMA 50`, `Volume` và 2 đường nét đứt `Support / Resistance`) đính kèm vào bài.
   - **Dự phòng (Phương án 2):** Nếu Phương án 1 gặp lỗi kết nối, tự động chuyển sang kho ảnh báo chí thật độ phân giải cao theo chủ đề (`TOPIC_PHOTO_POOL`).
6. **Tự Động Đăng (Không Cần Duyệt Thủ Công) & Cân Bằng 5 Nhóm Nội Dung (Ưu Tiên 82% Kiến Thức, Lợi Nhuận Cho Người Mới & Thảo Luận — Tin Tức & Dự Báo Xu Hướng 18%):**
   - **30% Kiến thức Thực chiến & Bài toán Lợi nhuận từ YouTube KOL (`kol`):** Bài toán kiếm đều `$30–$50/ngày` từ 20–30 pips, công thức `R:R 1:2.5` (thắng 4/10 lệnh vẫn lãi đậm), mẹo đợi quét râu thanh khoản trước khi vào lệnh.
   - **25% Chủ đề Thảo luận Thực chiến & Tâm lý Lợi nhuận (`reddit`):** So sánh đánh ăn chắc 20–30 pips/ngày vs gồng dài, cách chia Lot an toàn cho tài khoản vốn `$500–$1,000`, khung giờ vàng dễ kiếm lời nhất cho người bận đi làm.
   - **15% Mẹo Giữ lãi, Rút lãi & Kỷ luật từ TikTok KOL (`tiktok`):** Quy tắc rút 50% lợi nhuận về ngân hàng cuối tuần, chỉ trích 30% lãi sáng/chiều để đánh phiên Mỹ.
   - **12% Tối ưu Lợi nhuận ròng qua Điều kiện Giao dịch VT Markets Việt Nam (`vt`):** Bài toán cộng dồn tiền hoàn phí Backcom 100% + tài khoản Raw ECN, mẹo nhìn sẵn số tiền Lãi/Lỗ bằng USD trên TradingView trước khi vào lệnh.
   - **Tối đa 18% Tin tức Vĩ mô & Phân tích định lượng (`tintuc`):** Chỉ lên khi có tin thực sự quan trọng kèm giải mã cơ hội kiếm lời cụ thể.

## 2. Bộ 7 Thư Viện Mã Nguồn Mở Tích Hợp Trong Hệ Thống
- `g4f` (`xtekky/gpt4free` — `Yqcloud` / `ChatGPT`): Bộ não ngôn ngữ lớn (GPT-4 / ChatGPT) tư duy linh hoạt và trả lời tự nhiên theo 3 cấp độ người hỏi (`BEGINNER`, `EXPERIENCED`, `BROKER_LEAD`), tuyệt đối không trả lời rập khuôn.
- `tradingview_ta` (`AnalyzerREST/python-tradingview-ta`): Quét chỉ báo định lượng Spot `XAU/USD` & `DXY` (`RSI`, `EMA20`, `EMA50`, `Bollinger Bands`, `BUY/SELL Summary`).
- `mplfinance` (`matplotlib/mplfinance`) + `pandas`: Vẽ biểu đồ nến `XAU/USD` thời gian thực chuẩn giao diện TradingView Dark Mode.
- `trafilatura`: Bóc tách toàn văn dữ liệu bài báo quốc tế.
- `feedparser`: Đọc và chuẩn hóa luồng RSS tài chính quốc tế.
- `youtube-transcript-api`: Bóc tách phụ đề video YouTube KOL & Podcast nhận định Vàng, Dầu hàng ngày.
- `curl_cffi` + Cloudflare DoH `1.1.1.1`: Giả lập TLS Chrome vượt chặn DNS nhà mạng Việt Nam.

## 3. Các File Trong Repo GitHub
- Engine nội dung (các dạng bài, LLM, kho dự phòng): `content_engine.py`
- Bộ quét nguồn, phân tích định lượng & xuất bản: `news_and_kol_radar.py`
- Bot trực nhóm, lịch đăng & lệnh admin: `bot_truc_nhom.py`
- State do bot tự commit về repo: `bot_state.json`, `content_balance_state.json`, `daily_buzz_pool.json`, `whitelist.json`
- Secrets cấu hình tại GitHub (Settings → Secrets → Actions): `VT_BOT_TOKEN` (bắt buộc), `GEMINI_API_KEY` (khuyến nghị)

## 4. Lịch Tự Động & Lệnh Điều Khiển Trên Telegram
- Nhóm `VT Markets | Thảo Luận & Thực Chiến` (`-1004375233328`), múi giờ `Asia/Ho_Chi_Minh`. Lịch định nghĩa trong `SCHEDULE` của `bot_truc_nhom.py`:
  - T2–T6: `08:30` tin vĩ mô (`news`), `10:15` poll, `14:30` tóm tắt video KOL từ phụ đề thật (`kol_insight`), `16:00` câu hỏi tình huống, `19:15` xoay vòng Reddit / giải thích thuật ngữ / VT Markets.
  - T7 `10:00` tổng kết tuần; CN `19:00` poll đầu tuần.
  - Nhóm im ắng trên 5 giờ: thả câu hỏi gợi chuyện ngắn.
- Lệnh admin (gõ trong nhóm `[NỘI BỘ] Báo Khách & Sale`): `/tintuc`, `/kol`, `/tiktok`, `/reddit`, `/vt`, `/goichuyen`, `/them`, `/xoa`, `/danhsach`.

## 5. Quy Trình Cập Nhật Skill (Chỉ Qua GitHub)
1. Clone/pull repo về thư mục tạm (không chạy bot): `git pull --rebase --autostash origin main` (bot cloud tự commit state nên repo luôn đi trước).
2. Sửa code, chạy `python -m py_compile` để kiểm tra cú pháp. Không chạy bot thật khi test (dùng mock `publish_post`), và hoàn tác các file state bị ghi đè (`git checkout -- daily_buzz_pool.json content_balance_state.json`).
3. Đồng bộ `SKILL.md` sang `C:\Users\PHONG\.gemini\config\skills\vt-community-radar\SKILL.md`.
4. `git add`, `git commit`, `git push origin main`. Push kích hoạt workflow, bot mới chạy trên máy chủ GitHub.
5. Xem kết quả ở tab Actions của repo.

## 6. Lưu Ý Vận Hành
- **Chỉ MỘT instance được gọi `getUpdates`:** chỉ chạy trên GitHub Actions, không chạy bot trên máy local (lỗi `409 Conflict`, đăng trùng, state lệch).
- **Lưu state:** `bot_state.json` bị ghi liên tục nên `git pull --rebase` luôn dùng `--autostash` và retry push; mọi slot và lúc thoát đều gọi `sync_git_state()`.
- **Đăng lỗi:** slot lỗi chờ 10 phút (`SLOT_RETRY_COOLDOWN`) mới thử lại, tránh quét lại toàn bộ nguồn liên tục.
- **Repo luôn đi trước bản sao trên máy** vì bot cloud tự commit state: luôn `git pull --rebase --autostash origin main` trước khi sửa.

## 7. Nội Dung Mới (v2 — thay thế mục lịch ở phần 4 và tỷ lệ 5 nhóm ở phần 1.6)
- Engine: `content_engine.py`. Nhiều dạng bài: tin vĩ mô thật, tóm tắt video KOL **từ phụ đề thật** (không có phụ đề thì không đăng, tuyệt đối không gán lời cho KOL), poll (`sendPoll`), câu hỏi tình huống, giải thích thuật ngữ, Reddit (chỉ bài có nội dung thật), tổng kết cuối tuần.
- LLM lỗi thì dùng kho dự phòng viết sẵn trong `content_engine.py` (poll, tình huống, thuật ngữ). Bot im ắng trên 5 giờ mới thả câu hỏi gợi chuyện.

## 8. Tự Chăm Sóc Cộng Đồng (Không Cần Gõ Lệnh)
- Bot tự đăng theo lịch ở mục 4; các lệnh admin chỉ là tùy chọn khi muốn đăng thêm ngay.
- **Chào thành viên mới** ngay trong nhóm (1 tin duy nhất kể cả nhiều người vào cùng lúc), đồng thời vẫn báo nội bộ cho Sale.
- **Câu hỏi chưa ai đáp:** sau 8 phút không có người khác trả lời, bot tự trả lời (dẫn nguồn khách quan, không khuyên mua/bán). Giới hạn 6 lần/ngày, cách nhau tối thiểu 15 phút, chỉ 07:00–23:00, bỏ qua câu hỏi quá 4 giờ.
- Vẫn trả lời ngay khi được tag, gọi "bot" hoặc reply vào tin của bot.
