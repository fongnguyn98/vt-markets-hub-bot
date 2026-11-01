---
name: vt-community-radar
description: Vận hành và sửa bot Telegram VT Markets Hub cùng pipeline nội dung chống spam (review video, mổ xẻ thảo luận, hồ sơ rủi ro, tranh luận có poll). Tích hợp 5 repo mã nguồn mở (danielmiessler/fabric, maxbachmann/RapidFuzz, LIAAD/yake, yt-dlp/yt-dlp, adbar/trafilatura). Dùng khi thay đổi nguồn, định dạng bài, bộ kiểm tra, lịch đăng hoặc kiểm duyệt của repo fongnguyn98/vt-markets-hub-bot. Bot chạy trên GitHub Actions, không chạy trên máy local.
---

# VT Markets Hub: Bot & Pipeline Nội Dung Chống Spam

Skill này dành cho người hoặc AI sửa repo. Bot đang chạy không đọc file này: quy tắc có hiệu lực nằm trong `validators.py`, các prompt trong `content_pipeline.py` và `tests/`. Đổi quy tắc thì sửa code và thêm test, không chỉ sửa skill.

## Hệ sinh thái Repo Mã nguồn mở tích hợp

1. **`danielmiessler/fabric` (~40.000 ⭐ — Patterns `extract_wisdom`, `analyze_claims`, `rate_content`):**
   - Chấm điểm mật độ kiến thức thực chiến (`quality_score` thang 1–10; dưới 7 tự động loại bỏ các bài đạo lý chung chung hoặc khoe lãi).
   - Bóc tách theo cấu trúc 3 tầng: **Luận điểm cốt lõi (Core Mechanics)** $\rightarrow$ **Kiểm chứng bằng chứng & Điểm mù thực chiến (Claims vs Blindspots)** $\rightarrow$ **Câu hỏi thảo luận trải nghiệm thật**.
2. **`maxbachmann/RapidFuzz` (~3.500 ⭐ — C++ Fuzzy String Matching & Token Alignment):**
   - Đối chiếu câu trích dẫn tiếng gốc (`quote_in_source`) kết hợp chuẩn hóa dấu câu và `partial_ratio >= 88%` để xác thực 100% trích dẫn thật từ phụ đề tự động mà không loại nhầm vì khác dấu câu.
3. **`LIAAD/yake` (Unsupervised Keyword & Signal Density Extractor):**
   - Chạy bộ lọc mật độ tín hiệu (`signal_density_ok`) trên văn bản gốc trước khi gọi LLM để loại bỏ bài đăng ảnh meme, tâm sự ngoài lề hoặc hỏi đáp cụt lủn trên Reddit.
4. **`yt-dlp/yt-dlp` (~105.000 ⭐) + `jdepoix/youtube-transcript-api`:**
   - Lấy phụ đề YouTube hai tầng (ưu tiên phụ đề thủ công $\rightarrow$ phụ đề tự động qua `youtube-transcript-api` $\rightarrow$ fallback `yt-dlp` đa client `ios/android/web`).
5. **`adbar/trafilatura` + `lexiforest/curl_cffi`:**
   - Bóc tách toàn văn tài liệu pháp lý/hồ sơ rủi ro (`CASE_SOURCES`) và vượt tường lửa TLS bằng Chrome fingerprint impersonation.

## Kiến trúc

Pipeline chỉ thêm bài vào hàng đợi. Bot chỉ đăng từ hàng đợi (ưu tiên bài phân tích chuyên sâu trước, khảo sát `poll` sau) và không gọi LLM.

`content_pipeline.py` $\rightarrow$ tìm nguồn $\rightarrow$ lọc mật độ tín hiệu (`YAKE`) $\rightarrow$ lấy phụ đề hoặc toàn văn $\rightarrow$ LLM trả JSON kèm điểm chất lượng & câu gốc (`Fabric` pattern) $\rightarrow$ code kiểm câu gốc (`RapidFuzz`) rồi dựng bài ngắn gọn $\rightarrow$ `validators.py` $\rightarrow$ `content_queue/`

`bot_truc_nhom.py` $\rightarrow$ chạy lớp kiểm duyệt tự động (`pre_publish_audit`: `validators.check_item` + `check_schedule` + `detect_violation`) $\rightarrow$ đạt chuẩn thì tự động đăng ngay trong khung giờ $\rightarrow$ ghi `content_queue_state.json`

Không có bài đạt thì bot im lặng. Không thêm bài dự phòng để lấp lịch.

| File | Vai trò |
|---|---|
| `bot_truc_nhom.py` | Đăng từ hàng đợi, lời chào, kiểm duyệt, lệnh tiện ích, đo lường |
| `content_pipeline.py` | Tìm nguồn, lọc YAKE, trích dữ kiện theo mẫu Fabric, dựng bài, kho poll |
| `validators.py` | Kiểm tra từng bài (RapidFuzz quote, số liệu, điểm chất lượng) và quy tắc đa dạng |
| `content_queue.py`, `content_queue/`, `content_queue_state.json` | Hàng đợi và trạng thái |
| `metrics.json` | Vào, rời, hoạt động theo ID đã băm |
| `.github/workflows/content_pipeline.yml` | Nạp hàng đợi mỗi 6 giờ |
| `.github/workflows/vt_bot_247.yml` | Chạy bot |

Secrets: `VT_BOT_TOKEN`, `GEMINI_API_KEY` (có hỗ trợ JSON fallback tự động qua `ALLOW_FREE_LLM_FALLBACK=1` và kiểm chứng 100% qua `validators.py`).

## Quy tắc nội dung

- **Không cam kết lợi nhuận, không kêu gọi vốn, không ủy thác, không gọi lệnh, không gửi link giới thiệu.** Thu nhập chỉ được xuất hiện trong mục nhận định chưa kiểm chứng của một bài review.
- **Không dùng pip hay thu nhập làm mồi** ở tiêu đề và các dòng đầu; poll không xoay quanh pip, lãi lỗ hay dự đoán giá.
- **Không bịa:** không có phụ đề thì coi như chưa xem video. Không dựng người, lệnh hay tình huống. Mỗi câu gốc phải khớp nguồn, mỗi con số phải có trong nguồn (hỗ trợ đối chiếu cả số viết bằng chữ tiếng Anh).
- **Không giả người:** bài ghi rõ AI. Không dùng tài khoản giả hay số phiếu giả. Kết quả poll lấy từ Telegram.
- Xưng hô "bạn". Trình bày cô đọng, sắc bén, chia rõ luận điểm và điểm mù thực chiến, không viết kiểu biên bản hành chính rườm rà.

## Năm định dạng

| Kind | Nguồn | Giới hạn |
|---|---|---|
| `video_review` | Phụ đề YouTube trong 365 ngày (loại video dự báo ngày/tuần), kênh trong `Sheet2_Kenh_YouTube_KOL_Trading.csv` | Một tác giả tối đa 1 bài/14 ngày |
| `thread_review` | Thread Reddit có bài gốc $\ge 250$ ký tự, ít nhất 20 bình luận sâu và hai phía lập luận thật | Không chứa tên người dùng |
| `case_study` | Tài liệu trong `CASE_SOURCES` (FTC, VietNamNet...) | Vụ chưa có bản án ghi "bị cáo buộc" |
| `debate` | Thread có hai phía, kèm poll, đăng kết quả sau 48 giờ | Tối đa 1/tuần |
| `poll` | `POLL_BANK`, 6 nhóm luân phiên | Tối đa 2/tuần, tính cả poll tranh luận |

Tối đa 2 bài/ngày, cách nhau ít nhất 4 giờ, trong hai khung 09:00-11:00 và 19:30-21:30.

## Lệnh

- Thành viên: `/tinhlenh`, `/chiphi`, `/kiemtra`, `/thuvien`, `/baocao`.
- Chủ nhóm (gõ trong nhóm nội bộ): `/tamdung`, `/tieptuc`, `/thongke`, `/hangdoi`, `/ghim`, `/them`, `/xoa`, `/danhsach`, `/donrac [id1 id2 ...]`.

## Sửa và triển khai

1. `git pull --rebase --autostash origin main` vì bot tự commit state.
2. `python -m unittest discover -s tests`.
3. Xem bài không ghi hàng đợi: `python content_pipeline.py --dry-run`.
4. Đồng bộ `SKILL.md` sang `C:\Users\PHONG\.gemini\config\skills\vt-community-radar\SKILL.md`.
5. Push lên `main` sẽ khởi động lại bot thật. Không chạy `bot_truc_nhom.py` trên máy vì gây `409 Conflict`.
