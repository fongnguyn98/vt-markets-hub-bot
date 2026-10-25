@echo off
chcp 65001 >nul
cd /d "D:\CÁC LOẠI WORKFLOW & SKILL\HE_THONG_CONG_DONG_VT_MARKETS_HUB"

echo ============================================================================
echo   ĐẨY HỆ THỐNG BOT VT MARKETS HUB LÊN GITHUB ACTIONS CHẠY 24/7 (CLOUD)
echo ============================================================================
echo.
set /p REPO_URL="Nhập đường link GitHub Repo của anh (ví dụ https://github.com/username/vt-bot.git): "

if "%REPO_URL%"=="" (
    echo [!] Anh chưa nhập link GitHub Repo.
    pause
    exit /b 1
)

git init
git branch -M main
git config user.name "Phong Nguyen"
git config user.email "phong@vtmarketshub.local"
git add .
git commit -m "Deploy VT Markets Hub 24/7 Cloud Bot"
git remote remove origin 2>nul
git remote add origin %REPO_URL%
git push -u origin main --force

echo.
echo [+] Đã đẩy toàn bộ hệ thống lên GitHub Actions thành công!
echo [+] Đang tạm dừng bộ chạy trùng trên máy tính cá nhân để nhường quyền 100%% cho GitHub Cloud...
schtasks /Delete /TN "VT_Markets_Bot_Watchdog" /F 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *bot_truc_nhom*" 2>nul

echo.
echo ============================================================================
echo   HOÀN TẤT! BOT ĐÃ CHẠY 24/7 TRÊN GITHUB ACTIONS (TẮT MÁY TÍNH VẪN CHẠY)
echo ============================================================================
pause
