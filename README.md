<h1 align="center">
  <img src="Yolbulan.png" alt="Yolbulan ikonu" width="64" height="64">
  Yolbulan
</h1>

<p align="center">A Windows app that sorts videos into folders based on filenames or locally transcribed speech.</p>

Yolbulan, Windows'ta videoları dosya adında veya konuşmasında geçen terimlere göre alt klasörlere ayırır. Taşıma öncesinde sonucu gösterir ve onay ister. Konuşma analizi yerel Whisper modeliyle yapılır; videolar harici analiz servisine gönderilmez.

## Başlatma

ZIP'i çıkarıp `KUR_VE_BASLAT.cmd` dosyasını çalıştırın. İlk açılışta Python bağımlılıkları kurulur. Kaynak klasörü ve kuralları ana ekrandan seçin. Dosya adıyla ayırma ya da dosya adı + ses analizi modlarından birini kullanın.

## Windows EXE derleme

Windows'ta `DERLE.cmd` dosyasını çalıştırın. Exe dosyası `dist\Yolbulan\Yolbulan.exe` dizininde oluşur. EXE portatiftir: ayarlar ve transkriptler **EXE'nin yanındaki `calisma_verisi`** klasöründe tutulur.
`ffmpeg.exe` pakete eklenmez; mevcut ses çözümü PyAV kullandığı için harici `ffmpeg.exe` çağrılmaz.

Kurallar, modlar, transkript, CUDA kurulumu, derleme ve geri alma: [KULLANIM.md](KULLANIM.md).

## Lisans

MIT
