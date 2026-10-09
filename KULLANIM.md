# Yolbulan — Kullanım ve kurulum

Videoları dosya adına ve konuşma içeriğine göre klasörlere ayırır. Whisper konuşmayı yerel olarak yazıya döker; LM Studio üzerinde çalıştırdığınız yerel metin modeli içeriği yorumlar. Görüntüyü incelemez. Transkript yalnızca belirttiğiniz `localhost` veya yerel ağ IP adresine gönderilir. Whisper modeli ilk kurulumda indirilir.

## Masaüstü arayüzü

Windows'ta ZIP'i çıkarın ve **`KUR_VE_BASLAT.cmd` dosyasına çift tıklayın**. İlk çalıştırmada Python ortamı ve paketler kurulur, ardından arayüz açılır. Sonraki açılışlarda aynı dosyaya çift tıklayın. Python 3 ve ilk kurulumda internet gerekir. Hata olursa pencere kapanmaz. Var olan `.venv` ve `calisma_verisi` klasörlerini koruyun.

## EXE derleme (Windows)

Kaynak kod klasöründeki **`DERLE.cmd` dosyasına çift tıklayın**. Komut, Python paketlerini ve PyInstaller'ı kurup `dist\Yolbulan\Yolbulan.exe` oluşturur. Derlemeden önce EXE'yi kapatın. Windows EXE yalnız Windows üzerinde derlenir. `dist\Yolbulan` içindeki `_internal` klasörü dahil tüm dosyalar uygulamanın parçasıdır; yalnız EXE'yi tek başına kopyalamayın. Whisper modelleri EXE'ye paketlenmez; ilk ses analizinde indirilir ve sonra yerel önbellekten kullanılır.

Derlenen uygulama ayar, transkript ve taşıma kayıtlarını **`dist\Yolbulan\calisma_verisi`** altında, `Yolbulan.exe` dosyasının yanında saklar. İlk derlemede kaynak kod klasöründeki `calisma_verisi` bu konuma kopyalanır. Sonraki derlemelerde derlenmiş uygulamanın `calisma_verisi` klasörü korunur ve önceliklidir. Derleme önce ayrı bir geçici klasörde tamamlanır; hata olursa eski `dist\Yolbulan` değiştirilmez. Taşımak veya yedeklemek için `dist\Yolbulan` klasörünün tamamını kopyalayın. Kaynak koddan başlatırken kaynak kod klasöründeki `calisma_verisi` kullanılmaya devam eder. `%LOCALAPPDATA%\Yolbulan` oluşturulmaz.

`ffmpeg.exe` EXE paketine alınmaz. Yolbulan'ın mevcut ses analizi harici FFmpeg komutunu çağırmaz: faster-whisper, PyAV'ı kullanır; PyAV'ın gerekli yerel kitaplıkları uygulama paketinde bulunur. Makinenizdeki FFmpeg PATH ayarını değiştirmeye gerek yoktur; bu sürümde `ffmpeg.exe` PATH'den okunmaz. GPU kullanımı için gereken CUDA/cuDNN kitaplıkları ayrı gereksinimdir; arayüzdeki CUDA DLL klasörünü kullanabilirsiniz.

PowerShell'den doğrudan açmak için:

```powershell
./.venv/Scripts/python.exe gui.py
```

### Ana ekran

Her şey tek ekrandadır. Üstte kaynak klasör ve çalışma modu, altında üç işlem düğmesi bulunur. Düğmeler birbirinden bağımsızdır; her biri yalnızca adındaki işi yapar:

- **Adları tara:** Klasörü tarar ve dosya adlarını kurallarla eşleştirir. Hiçbir dosyayı taşımaz. Kaynak klasörün hemen altındaki hedef klasörler (kural klasörleri, `Incelenecekler`, `eslesme_yok`) taranmaz; daha derindeki aynı adlı klasörler taranır.
- **Sesi analiz et (N):** `Analiz bekliyor` durumundaki N videoyu Whisper ile yazıya döker, ardından LM Studio ile değerlendirir. **Durdur**, geçerli video veya LM Studio isteği bitince analizi durdurur; kalan videolar yeniden `Analiz bekliyor` olur.
- **Seçilen N videoyu taşı:** İşaretli videoları seçtiğiniz hedef alt klasöre taşır. Analiz sürerken de kullanılabilir; analiz sırasındaki videolar işaretlenemez.

**Kurallar** ve **Ayarlar** düğmeleri aynı pencerenin iki sekmesini açar. Değişiklikler **Kaydet** ile uygulanır; kurallar kaydedilirken doğrulanır. Kurallar değiştiyse dosya adı sonuçlarını güncellemek için yeniden **Adları tara**'ya basın.

### Liste

Taranan bütün videolar tek listededir. Üstteki filtreler (`Tümü`, `Ad eşleşti`, `Ses eşleşti`, `Eşleşme yok`, `Analiz bekliyor`, `Hata`) sayılarıyla birlikte listeyi daraltır; sağdaki kutu dosya adında arar. Sütun başlığına tıklayarak sıralayabilirsiniz.

- **Hedef** sütunundan klasör seçince video işaretlenir; `— yerinde kalsın` seçince işaret kalkar. Hedefi olmayan video işaretlenemez.
- Dosya adı veya ses eşleşmesi tek kurala uyuyorsa hedef o kuralın klasörüdür ve video işaretli gelir. Birden çok kurala uyuyorsa hedef `Incelenecekler` olur.
- Ses analizinde hiçbir kurala uymayan videolar `Eşleşme yok` olur, işaretli ve `eslesme_yok` hedefiyle gelir; taşınmasını istemediklerinizin işaretini kaldırın. `Yalnızca dosya adı` modunda eşleşmeyenler işaretsiz gelir ve yerinde kalır.
- Birden çok satırı seçip **Boşluk** tuşuyla işaretleyebilir veya işareti kaldırabilirsiniz. Sağ tık menüsünden seçili satırlara toplu hedef verebilir, dosya adıyla eşleşmiş bir videoyu **Ses analizine ekle** ile analiz sırasına alabilirsiniz.
- **Görünenleri işaretle**, filtrede görünen ve hedefi seçili videoları işaretler. **İşaretleri temizle** hedefleri korur.
- Taşınan videolar listeden kalkar. Taşınamayanlar `Taşınamadı` durumunda kalır; nedeni üzerine gelince görünür.

**Son taşımayı geri al**, en son taşıma işleminde taşınan ve sonrasında değişmemiş videoları eski yerine döndürür ve listeye geri ekler. Tekrar basınca bir önceki taşıma işlemine geçer. Taşıma veya analiz sürerken geri alma kullanılamaz.

Listenin altındaki **Günlük** satırı son mesajı gösterir; tıklayınca bütün kayıt açılır.

**Çalışma modu:** `Dosya adı + ses analizi` modunda dosya adıyla eşleşmeyen videolar `Analiz bekliyor` olur. `Yalnızca dosya adı` modunda bunlar `Eşleşme yok` olur; ses analizi düğmeleri gizlenir, Whisper ve LM Studio çalışmaz. Seçim açılışlar arasında hatırlanır.

Taşıma ve geri alma aynı disk bölümündeyse dosyayı yeniden adlandırarak yapılır; büyük videonun tamamı kopyalanmaz. Ayrı disk bölümleri arasındaki işlemlerde kopyalama gerekir. Hedefte aynı adlı dosya varsa üzerine yazılmaz. Alt klasörlerdeki videolar hedefte tek klasörde toplanır; aynı adlı ikinci video `Taşınamadı` olur.

### Kurallar

Her kural satırında **Dosya adı terimleri** ve **Ses içeriği tanımı (AI)** birbirinden bağımsızdır; ikisi de aynı hedef alt klasöre yönlendirir. Birini boş bırakabilirsiniz. Ses aşamasında anahtar sözcük eşleşmesi zorunlu değildir: model bütün transkripti zaman damgalı parçalarda okuyup her klasörün tanımını sınar. Tek bir isteğe bütün video sığdırılmaz: varsayılan olarak yaklaşık 12.000 karakterlik pencereler kullanılır ve komşu pencereler birbirleriyle örtüşür. Böylece parçaların sınırındaki konuşmalar birlikte görülebilir; birbirinden çok uzak iki bölüm tek seferde görülmez. İlişki birden fazla konuşma satırından anlaşılıyorsa model birden fazla birebir alıntı döndürebilir. **Transkript penceresi** ayarından parça boyutunu değiştirebilirsiniz; geniş pencere seçilen LM Studio modelinde yeterli context gerektirir. Önceki sürümün `speech_terms` alanındaki sözcükler ilk açılışta içerik tanımı alanına virgülle yazılır; daha iyi sonuç için bunları açıklayıcı cümlelere dönüştürün.

**Dosya adı engelleri (−)** virgülle ayrılan negatif terimlerdir. Bir hedefin dosya adı terimi eşleşse bile, aynı hedefin engellerinden biri dosya adında geçiyorsa o hedef elenir; diğer hedefler etkilenmez. Örneğin `tarık_doktor.mp4` için Video_1'in dosya adı terimi `tarık`, Video_2'nin dosya adı terimi `doktor` ve Video_2'nin dosya adı engeli `tarık` ise yalnız Video_1 eşleşir. Ses analizinde negatif terim kullanılmaz.

Dosya adı araması terimi adın herhangi bir yerinde bulur: `video`, `videoyedi.mp4` ile eşleşir. `example text` ve `example.text`, dosya adındaki `example.text` ile eşleşir. Daha uzun, tam kelime olarak geçen bir eşleşmenin içinde kalan parça eşleşmesi elenir. Örneğin `videoplayer.mp4` için `video`, `player`, `videoplayer` ayrı klasör kurallarıysa `videoplayer` kazanır. Birbirinin içinde olmayan eşleşmeler korunur: `uzaylılar ve sanal makine.mp4` iki kurala uyar ve `Incelenecekler` hedefini alır.

### Durumlar ve transkript

`Durum` sütunu `Ad eşleşti`, `Ses eşleşti`, `Eşleşme yok`, `Analiz bekliyor`, `Sırada`, `Model yükleniyor`, `Yazıya dökülüyor`, `LM Studio değerlendiriyor`, `Taşınıyor…`, `Taşınamadı` veya `Hata` gösterir. Bir ses eşleşmesinin klasörü ve zamanı **Eşleşen** sütunundadır; modelin sunduğu transkript alıntısı üzerine gelince görünür. Sunucu hatası, geçersiz yanıt veya transkriptte bulunmayan alıntı durumunda video `Hata` kalır ve otomatik olarak bir klasöre seçilmez. Model sınıflandırması kusursuz değildir; taşımadan önce sonuçları inceleyin.

`Metin` sütunundaki **Aç** düğmesi yalnız transkripti olan videolarda görünür ve transkripti ayrı pencerede zaman damgalarıyla açar. Her konuşma satırı dönüşümlü arka planla ayrılır; doğrulanan model alıntıları ve dosya adı terimleri vurgulanır. Pencere ilk eşleşmeye kaydırılır; **Önceki** ve **Sonraki** düğmeleri eşleşmeler arasında dolaşır.

Profiller: **Hızlı** = small / batch 16 / beam 1; **Dengeli** = small / batch 8 / beam 5; **Hassas** = large-v3 / batch 8 / beam 5. Model, toplu iş boyutu, beam, GPU/CPU ve hesaplama türü **Ayarlar** sekmesinden değiştirilebilir; değişiklik profili `Özel` yapar. Model ilk kez seçildiğinde indirilir. GPU belleği yetmezse toplu iş boyutunu 8 → 4 → 1 azaltın. Büyük batch daha çok VRAM kullanır; kullanım yüzdesinin artması tek başına daha hızlı çalıştığı anlamına gelmez. Transkript önbelleği model ve işlem ayarlarına bağlıdır; bunlar değiştiğinde video yeniden çözülür. CUDA DLL'leri PATH içinde değilse **Ayarlar** sekmesindeki `CUDA DLL klasörü` alanından `cublas64_12.dll` ve `cudnn64_9.dll` dosyalarını içeren klasörü seçin. Seçim hatırlanır.

**LM Studio:** Local Server'ı açın ve bir metin modeli yükleyin. **Ayarlar** sekmesindeki IP/port alanlarına sunucunun adresini (`127.0.0.1:1234` varsayılan) yazın, **Modelleri getir** düğmesine basıp metin modelini seçin veya kimliğini elle yazın. Sunucu başka cihazdaysa yerel ağ IP adresini kullanın; LM Studio sunucusunun yerel ağ bağlantılarını kabul edecek şekilde açılması gerekir. Açık internetteki IP adresleri kabul edilmez. Transkript ve içerik tanımları bu seçili makineye gönderilir; aynı bilgisayarda tamamen yerel çalışmasını istiyorsanız `127.0.0.1` kullanın. **Thinking** alanında `Model ayarı` seçiliyse LM Studio'daki modelin kendi ayarı kullanılır; `Kapalı` seçilirse LM Studio'nun yerel `/api/v1/chat` arayüzüne `reasoning=off` gönderilir. Model bu seçeneği desteklemiyorsa hata gösterilir; uygulama gizlice thinking'i yeniden açmaz. Whisper ve LM Studio aynı GPU'yu kullanıyorsa işlem sıralıdır: önce Whisper, ardından metin modeli. Metin değerlendirmesi klasör sayısı ve video uzunluğu ile artar. Aynı dosya, Whisper ayarları, model, thinking seçimi, pencere büyüklüğü ve içerik tanımları değişmediyse sınıflandırma önbellekten okunur.

**JSON yeniden deneme:** Varsayılan değer `2`'dir; geçersiz JSON veya doğrulanamayan model cevabı gelirse aynı transkript penceresi en fazla iki kez daha sorulur (toplam en fazla üç istek). İkinci denemeden itibaren modele biçimi düzeltmesi gerektiği hatırlatılır. Sayıyı arayüzden `0–5` arasında değiştirebilirsiniz. Bağlantı hataları tekrar edilmez; son deneme de başarısız olursa video `Hata` durumunda kalır. Deneme sayısını değiştirmek başarılı sınıflandırma önbelleğini silmez. Çok sayıda tekrar istek sayısını ve analiz süresini artırabilir.

`gui.py` kaynak uygulamadır; bu pakette hazır `.exe` yoktur. Başlatıcı bir `.exe` derlemez ve ilk çalıştırmada paketleri indirir.

## Elle kurulum (isteğe bağlı)

1. Python 3.10–3.12 kurulu olsun. PowerShell'de `py -3 --version` ile kontrol edin. faster-whisper ses çözme için kendi PyAV paketini kullanır; arayüz için FFmpeg PATH gerektirmez.
2. Bu klasörde PowerShell açıp `py -3 -m venv .venv` çalıştırın.
3. `./.venv/Scripts/python.exe -m pip install -r requirements.txt` çalıştırın. CUDA kullanımı için [faster-whisper belgelerindeki](https://github.com/SYSTRAN/faster-whisper#gpu) güncel cuBLAS/cuDNN gereksinimlerini de karşılayın; kurulu değilse arayüzden CPU seçin.
4. Kural ve klasörleri arayüzde girin.

## Sınırlar

Sesi yazıya dökme hataları ve modelin yanlış yorumu sonuçları etkiler. Seslendirilmeden sadece ekranda görünen öğeler saptanamaz. Taşıma sırasında video başka programca değiştiriliyorsa aynı anda düzenlemeyin. İlk denemeyi az sayıda videonun kopyasıyla yapın.
