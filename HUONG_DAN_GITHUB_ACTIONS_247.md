# HƯỚNG DẪN CHẠY BOT 24/7 TRÊN GITHUB ACTIONS (TẮT NGUỒN MÁY TÍNH VẪN CHẠY)

Toàn bộ cấu hình **GitHub Actions 24/7** đã được cài đặt sẵn tại:
- Workflow tự động chạy liên tục 24/7: [`.github/workflows/vt_bot_247.yml`](file:///D:/CÁC%20LOẠI%20WORKFLOW%20&%20SKILL/HE_THONG_CONG_DONG_VT_MARKETS_HUB/.github/workflows/vt_bot_247.yml)
- Danh sách thư viện đám mây: [`requirements.txt`](file:///D:/CÁC%20LOẠI%20WORKFLOW%20&%20SKILL/HE_THONG_CONG_DONG_VT_MARKETS_HUB/requirements.txt)
- Script đẩy tự động 1-Click: [`DEPLOY_LEN_GITHUB_ACTIONS_247.cmd`](file:///D:/CÁC%20LOẠI%20WORKFLOW%20&%20SKILL/HE_THONG_CONG_DONG_VT_MARKETS_HUB/DEPLOY_LEN_GITHUB_ACTIONS_247.cmd)

---

## Cơ Chế Vận Hành 24/7 Trên GitHub Actions
1. **Tự động nối tiếp chu kỳ 24/24:**
   - Mỗi phiên GitHub Actions chạy liên tục `bot_truc_nhom.py --max-runtime-seconds 19500` (5 tiếng 25 phút).
   - Khi kết thúc phiên, Workflow tự động lưu trạng thái (`bot_state.json`, `content_balance_state.json`, `whitelist.json`) về lại nhánh `main` và tự kích hoạt phiên tiếp theo ngay lập tức (`gh workflow run vt_bot_247.yml` + lịch `cron: '*/20 * * * *'`).
   - Cấu hình `concurrency: cancel-in-progress: false` đảm bảo tại mọi thời điểm chỉ có **duy nhất 1 tiến trình Bot** hoạt động, không bao giờ bị xung đột.
2. **Múi giờ chuẩn Việt Nam (`Asia/Ho_Chi_Minh` — UTC+7):**
   - Máy chủ Ubuntu trên GitHub tự động chuyển sang giờ Việt Nam trước khi chạy nên các khung giờ `08:30`, `10:15`, `11:45`, `14:30`, `16:00`, `19:15`, `20:45` hoạt động chính xác tuyệt đối dù máy tính cá nhân của anh đang tắt nguồn.

---

## Cách Kích Hoạt Lên GitHub Trong 30 Giây
1. Tạo 1 Repository **Private (Riêng tư)** mới trên GitHub (ví dụ: `https://github.com/<ten-tai-khoan>/vt-markets-hub-bot.git`).
2. Vào mục **Settings $\rightarrow$ Actions $\rightarrow$ General $\rightarrow$ Workflow permissions** của Repo đó, tích chọn **"Read and write permissions"** rồi bấm **Save**.
3. Nhấp đúp chạy file [`DEPLOY_LEN_GITHUB_ACTIONS_247.cmd`](file:///D:/CÁC%20LOẠI%20WORKFLOW%20&%20SKILL/HE_THONG_CONG_DONG_VT_MARKETS_HUB/DEPLOY_LEN_GITHUB_ACTIONS_247.cmd), dán đường link Repo GitHub vào và bấm Enter — hệ thống sẽ tự động đẩy toàn bộ code lên GitHub, kích hoạt GitHub Actions chạy 24/7 và tự động tắt bộ chạy trùng trên máy tính cá nhân.
