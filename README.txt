DAĞ OTO MUHASEBE & SERVİS - V1

Kurulum:
1) Windows'ta Python 3.11+ kur.
2) Bu klasörde terminal aç.
3) pip install -r requirements.txt
4) python main.py

EXE oluşturmak:
build_exe.bat dosyasını çalıştır.
Oluşan dosya: dist\DagOtoAsistan\DagOtoAsistan.exe

Veritabanı:
Program ilk açılışta kullanıcının ana klasöründe
DagOtoAsistan\dag_oto.db oluşturur.

V1 özellikleri:
- Günlük servis kayıtları
- Müşteri/cari borç hesabı
- Plaka ve araç geçmişi
- Ödeme kaydı
- Parça kodu kataloğu ve stok
- Excel (.xlsx) içe aktarma
- Veritabanı yedekleme

Not:
Ford'un kapalı/özel servis sistemine doğrudan bağlantı için resmi API/erişim gerekir.
Kendi elindeki Ford parça kodu Excel/CSV kataloğu programa aktarılabilir.
