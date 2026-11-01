---
name: vt-community-radar
description: Vận hành và sửa bot Telegram VT Markets Hub cùng pipeline nội dung (review video, review thảo luận, case study, tranh luận có poll). Dùng khi thay đổi nguồn, định dạng bài, bộ kiểm tra, lịch đăng hoặc kiểm duyệt của repo fongnguyn98/vt-markets-hub-bot. Bot chạy trên GitHub Actions, không chạy trên máy local.
---

# VT Markets Hub: bot và pipeline nội dung

Skill này dành cho người hoặc AI sửa repo. Bot đang chạy không đọc file này: quy tắc có hiệu lực nằm trong `validators.py`, các prompt trong `content_pipeline.py` và `tests/`. Đổi quy tắc thì sửa code và thêm test, không chỉ sửa skill.

## Kiến trúc

Pipeline chỉ thêm bài vào hàng đợi. Bot chỉ đăng từ hàng đợi và không gọi LLM.

`content_pipeline.py` -> tìm nguồn -> lấy phụ đề hoặc toàn văn -> LLM trả JSON kèm câu gốc -> code kiểm câu gốc rồi dựng bài theo mẫu -> `validators.py` -> `content_queue/`

`bot_truc_nhom.py` -> xem trước ở nhóm nội bộ -> sau 60 phút không chặn thì đăng -> ghi `content_queue_state.json`

Không có bài đạt thì bot im lặng. Không thêm bài dự phòng để lấp lịch: đây từng là nguyên nhân tạo chuỗi bài "lệnh đang lãi X pip".

| File | Vai trò |
|---|---|
| `bot_truc_nhom.py` | Đăng từ hàng đợi, lời chào, kiểm duyệt, lệnh tiện ích, đo lường |
| `content_pipeline.py` | Tìm nguồn, trích dữ kiện, dựng bài, kho poll |
| `validators.py` | Kiểm tra từng bài và quy tắc đa dạng |
| `content_queue.py`, `content_queue/`, `content_queue_state.json` | Hàng đợi và trạng thái |
| `metrics.json` | Vào, rời, hoạt động theo ID đã băm |
| `.github/workflows/content_pipeline.yml` | Nạp hàng đợi mỗi 6 giờ |
| `.github/workflows/vt_bot_247.yml` | Chạy bot |

Secrets: `VT_BOT_TOKEN`, `GEMINI_API_KEY`.

## Quy tắc nội dung

- **Không cam kết lợi nhuận, không kêu gọi vốn, không ủy thác, không gọi lệnh, không gửi link giới thiệu.** Thu nhập chỉ được xuất hiện trong mục tuyên bố của một review, có nhãn chưa kiểm chứng.
- **Không dùng pip hay thu nhập làm mồi** ở tiêu đề và các dòng đầu; poll không xoay quanh pip, lãi lỗ hay dự đoán giá.
- **Không bịa:** không có phụ đề thì coi như chưa xem video. Không dựng người, lệnh hay tình huống. Mỗi câu gốc phải khớp nguồn, mỗi con số phải có trong nguồn.
- **Không giả người:** bài ghi rõ AI và bot. Không dùng tài khoản giả hay số phiếu giả. Kết quả poll lấy từ Telegram.
- Xưng hô "bạn". Phê bình luận điểm, không kết luận tác giả lừa đảo. Không đăng lại video hay nguyên transcript.

## Năm định dạng

| Kind | Nguồn | Giới hạn |
|---|---|---|
| `video_review` | Phụ đề YouTube trong 90 ngày, kênh trong tab YouTube của Sheet | Một tác giả tối đa 1 bài/14 ngày |
| `thread_review` | Thread Reddit có ít nhất 20 bình luận và hai phía thật | Không chứa tên người dùng |
| `case_study` | Tài liệu trong `CASE_SOURCES` | Vụ chưa có bản án ghi "bị cáo buộc" |
| `debate` | Thread có hai phía, kèm poll, đăng kết quả sau 48 giờ | Tối đa 1/tuần |
| `poll` | `POLL_BANK`, 6 nhóm luân phiên | Tối đa 2/tuần, tính cả poll tranh luận |

Tối đa 2 bài/ngày, cách nhau ít nhất 4 giờ, trong hai khung 09:00-11:00 và 19:30-21:30. TikTok chưa được dùng vì chưa có đường lấy phụ đề ổn định.

## Lệnh

- Thành viên: `/tinhlenh`, `/chiphi`, `/kiemtra`, `/thuvien`, `/baocao`.
- Chủ nhóm, gõ trong nhóm nội bộ khi cần: `/tamdung`, `/tieptuc`, `/thongke`, `/hangdoi`, `/ghim`, `/them`, `/xoa`, `/danhsach`.

Không cần gõ lệnh để vận hành: bot tự ghim tin giới thiệu một lần, tự kiểm tra quyền admin và chỉ báo khi thiếu, sáng thứ Hai tự gửi số liệu tuần. Pipeline tự chạy mỗi 6 giờ và khi code pipeline đổi trên `main`.

## Kiểm duyệt

Gỡ tin luôn kèm lý do. Lần đầu không khóa; lần thứ hai trong 7 ngày khóa 24 giờ và tự mở. Được gửi link biểu đồ, tin tức và nhắc tên sàn. Chặn link mời nhóm khác, link rút gọn, link giới thiệu, nội dung mời chào, kêu gọi vốn và cam kết lợi nhuận.

## Sửa và triển khai

1. `git pull --rebase --autostash origin main` vì bot tự commit state.
2. `python -m unittest discover -s tests`.
3. Xem bài không ghi hàng đợi: `python content_pipeline.py --dry-run`. Cần `GEMINI_API_KEY`.
4. Đồng bộ `SKILL.md` sang `C:\Users\PHONG\.gemini\config\skills\vt-community-radar\SKILL.md`.
5. Push lên `main` sẽ khởi động lại bot thật. Không chạy `bot_truc_nhom.py` trên máy vì gây `409 Conflict`.

## Lưu ý vận hành

- YouTube chặn phần lớn IP cloud nên khâu lấy phụ đề có thể lỗi trên GitHub Actions. Lý do loại được ghi trong log và gửi vào nhóm nội bộ khi không tạo được bài. Nếu lỗi kéo dài, chạy `python content_pipeline.py` trên máy ở nhà rồi commit `content_queue/`.
- Telegram chỉ giữ update 24 giờ; bot phải là admin thì mới nhận `chat_member`.
- Điều khoản GitHub Actions có vẻ chỉ cho dùng để phát triển và kiểm thử; về lâu dài nên chuyển bot sang máy chủ riêng.
