<h1 align="center"><img src="Yolbulan.png" alt="Yolbulan ikonu" width="64" height="64" align="absmiddle"> <sub><big>Yolbulan</big></sub></h1>

<p align="center">A Windows app that sorts videos into folders based on filenames or locally analyzed speech.</p>

Yolbulan, Windows'ta videoları dosya adı kurallarına veya konuşmalarının içeriğine göre alt klasörlere ayırır. Taşıma öncesinde sonucu gösterir ve onay ister. Konuşmaları yerel Whisper yazıya döker; yerel ağdaki LM Studio metin modeli içerik tanımlarına göre değerlendirir. Video ve transkript harici analiz servisine gönderilmez.

## Başlatma

ZIP'i çıkarıp `KUR_VE_BASLAT.cmd` dosyasını çalıştırın. İlk açılışta Python bağımlılıkları kurulur. Kaynak klasörü ve kuralları ana ekrandan seçin. Dosya adıyla ayırma ya da dosya adı + ses analizi modlarından birini kullanın.

## Windows EXE derleme

Windows'ta `DERLE.cmd` dosyasını çalıştırın. Çıktı `dist\Yolbulan\Yolbulan.exe` olur. EXE portatiftir: ayarlar ve transkriptler **EXE'nin yanındaki `calisma_verisi`** klasöründe tutulur. Başka bilgisayara taşırken `dist\Yolbulan` klasörünün tamamını kopyalayın. `ffmpeg.exe` pakete eklenmez; mevcut ses çözümü PyAV kullandığı için harici `ffmpeg.exe` çağrılmaz.

Kurallar, modlar, transkript, CUDA kurulumu, derleme ve geri alma: [KULLANIM.md](KULLANIM.md).

## Lisans

MIT
