@echo off
echo ============================================
echo  BUOC 1/3: Tim van ban moi...
echo ============================================
python src\tvpl\discover_documents.py
if %errorlevel% neq 0 (
    echo [LOI] discover_documents.py that bai. Kiem tra Chrome da mo chua.
    pause & exit /b 1
)

echo.
echo ============================================
echo  BUOC 2/3: Tai HTML tung van ban...
echo ============================================
python src\tvpl\fetch_document_html.py
if %errorlevel% neq 0 (
    echo [LOI] fetch_document_html.py that bai.
    pause & exit /b 1
)

echo.
echo ============================================
echo  BUOC 3/3: Trich xuat bang gia...
echo ============================================
python src\tvpl\parse_document_content.py
if %errorlevel% neq 0 (
    echo [LOI] parse_document_content.py that bai.
    pause & exit /b 1
)

echo.
echo ============================================
echo  XONG. Ket qua o: data\interim\parsed_documents.csv
echo ============================================
pause
