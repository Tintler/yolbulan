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

Kaynak klasörü seçin; hedef alt klasörleri ve dosya adı terimlerini ana ekranda girin. Ses aşaması istediğiniz hedefler için **Ses içeriği tanımı (AI)** alanını doldurun. Örneğin `Anne ile kızının aile bağları hakkında konuştuğu bir içerik` yazın. `1 · Dosya adlarını tara` düğmesi, transkripsiyon yapmadan dosya adında terim arar. Listede taşınacakları ve hedef alt klasörlerini kontrol edin. İlk onaydan sonra **dosya adı eşleşmeyenler ve işaretini kaldırdığınız ad eşleşmeleri** Whisper ile yazıya dökülür; LM Studio transkripti tüm içerik tanımlarına göre değerlendirir. İkinci listeden ses sonuçlarını ve alıntıları kontrol edip onaylayın. Birden çok kurala uyanlar başlangıçta `Incelenecekler` hedefini kullanır; satırdaki hedefi değiştirebilirsiniz. Ses analizi aşamasında işaretini kaldırdığınız videolar yerinde kalır. Taşınan dosyalar kaynak klasörün alt klasörlerine gider. Her taramada belirlediğiniz kural klasörleri, `Incelenecekler` ve `eslesme_yok` tarama dışında tutulur.

**Çalışma modu:** `Dosya adı + ses analizi` yukarıdaki iki aşamalı işlemdir. `Yalnızca dosya adı` seçildiğinde tarama aynı kuralları ve negatif dosya adı terimlerini kullanır. İşaretli eşleşmeleri onaylayıp taşır; işaretini kaldırdıklarınız ve eşleşmeyenler kaynakta kalır. Ses analizi, Whisper model yüklemesi ve CUDA kontrolü yapılmaz. Seçim açılışlar arasında hatırlanır. Modu değiştirdikten sonra, listede önceki ses aşaması varsa yeniden dosya adlarını tarayın.

Taşıma ve geri alma aynı disk bölümündeyse dosyayı yeniden adlandırarak yapılır; büyük videonun tamamı kopyalanmaz. Ayrı disk bölümleri arasındaki işlemlerde kopyalama gerekir. Hedefte aynı adlı dosya varsa üzerine yazılmaz.

Her kural satırında **Dosya adı terimleri** ve **Ses içeriği tanımı (AI)** birbirinden bağımsızdır; ikisi de aynı hedef alt klasöre yönlendirir. Birini boş bırakabilirsiniz. İkinci aşamada anahtar sözcük eşleşmesi zorunlu değildir: model bütün transkripti zaman damgalı parçalarda okuyup her klasörün tanımını sınar. Tek bir isteğe bütün video sığdırılmaz: varsayılan olarak yaklaşık 12.000 karakterlik pencereler kullanılır ve komşu pencereler birbirleriyle örtüşür. Böylece parçaların sınırındaki konuşmalar birlikte görülebilir; birbirinden çok uzak iki bölüm tek seferde görülmez. İlişki birden fazla konuşma satırından anlaşılıyorsa model birden fazla birebir alıntı döndürebilir. **Transkript penceresi** alanından parça boyutunu değiştirebilirsiniz; geniş pencere seçilen LM Studio modelinde yeterli context gerektirir. Önceki sürümün `speech_terms` alanındaki sözcükler ilk açılışta yeni içerik tanımı alanına virgülle yazılır; daha iyi sonuç için bunları açıklayıcı cümlelere dönüştürün. Kayıt ve yeniden tarama sonrasında yeni kurallar kullanılır.

**Dosya adı engelleri (−)** virgülle ayrılan negatif terimlerdir. Bir hedefin dosya adı terimi eşleşse bile, aynı hedefin engellerinden biri dosya adında geçiyorsa o hedef elenir; diğer hedefler etkilenmez. Örneğin `tarık_doktor.mp4` için Video_1'in dosya adı terimi `tarık`, Video_2'nin dosya adı terimi `doktor` ve Video_2'nin dosya adı engeli `tarık` ise yalnız Video_1 eşleşir. Ses analizinde negatif terim kullanılmaz. Eski kuralların engel alanları başlangıçta boştur.

Taranan bütün videolar listede kalır. `Durum` sütunu her video için `Taşındı`, `Analiz bekliyor`, `Model yükleniyor`, `Analiz ediliyor`, `LM Studio değerlendiriyor`, `Ses eşleşti`, `Eşleşme yok` veya `Hata` gösterir. İşlem ilerlemesi video ve metin parçası sayısıyla gösterilir. Bir eşleşmenin klasörü ve zamanı **Eşleşen** sütununda; modelin sunduğu transkript alıntısı üzerine gelince görünür. Sunucu hatası, geçersiz yanıt veya transkriptte bulunmayan alıntı durumunda video `Hata` kalır, otomatik olarak `eslesme_yok` klasörüne seçilmez. Model sınıflandırması kusursuz değildir; taşımadan önce önizlemeyi inceleyin.

Alt listedeki **Hedef alt klasör**, yalnız taşımaya seçilebilen satırlarda bir seçim kutusudur. Hedefi henüz olmayan veya taşınmayacak satırlarda `—` görünür; taşınan satırda gerçekten kullanılan klasör gösterilir. Ses aşamasında eşleşmeyenler seçilebilir duruma geçtiğinde varsayılan hedef `eslesme_yok` olur.

`Metin` sütunundaki **Aç** düğmesi kaydedilmiş transkripti zaman damgalarıyla gösterir. Transkript oluşturulmamışsa düğme pasiftir; yalnızca dosya adına göre taşınan videolarda transkript olmayabilir. Kural değişiklikleri yaklaşık 0,4 saniye sonra otomatik kaydedilir ve `Kaydedildi` yazısı görünür. İsterseniz `Kuralları kaydet` düğmesine basın. Eksik bırakılmış kural taslakları da kaydedilir; taramayı başlatırken kural doğrulaması yapılır.

Transkript penceresinde her zaman damgalı konuşmanın tamamı, uzun metin alt satıra taşsa bile, ana listedeki iki dönüşümlü arka plan rengiyle ayrılır; doğrulanan model alıntıları ayrıca vurgulanır. Pencere ilk eşleşmeye kaydırılır; **Önceki** ve **Sonraki** düğmeleri aynı transkriptteki eşleşmeler arasında dolaşır, sayaç konumu gösterir. Eşleşme yoksa düğmeler pasif kalır. `Durum` renkleri: taşındı yeşil, eşleşme yok sarı, hata kırmızı, devam eden işlem mavi, eşleşme mor. Seçilemeyen satırlarda aynı büyüklükte gri, devre dışı tik kutusu gösterilir; üzerine gelince nedeni yazılır. Kaynak klasörün yanındaki **Yenile**, aynı klasörü uygulamadan çıkmadan baştan tarar; kaynak klasörden taşınmış videoları listeden kaldırır ve yeni videoları ekler. Yenileme, sürmekte olan bir taşıma veya analiz tamamlandıktan sonra kullanılabilir.

Dosya adı araması terimi adın herhangi bir yerinde bulur: `video`, `videoyedi.mp4` ile eşleşir. `example text` ve `example.text`, dosya adındaki `example.text` ile eşleşir. Dosya adında tam kelime/ifade olarak bulunan terim, sözcük içindeki parça eşleşmelerinden önceliklidir; birden fazla tam eşleşmede uzun olan kazanır. Örneğin `videoplayer.mp4` için `video`, `player`, `videoplayer` ayrı klasör kurallarıysa `videoplayer` kazanır. Son kural yoksa iki parça eşleşmesi `Incelenecekler` hedefini seçer. Ses aşamasında tek tek sözcük aramak yerine içerik tanımları modele sorulur.

Ses analizi bittiğinde **Eşleşme yok** videoları ikinci onay listesinde varsayılan olarak işaretlidir ve hedefleri `eslesme_yok` alt klasörüdür. İstemediğiniz satırın işaretini kaldırabilirsiniz. Taşıma ancak ikinci onay düğmesine bastığınızda yapılır. `Yenile`, oluşturulan `eslesme_yok` klasörünü kaynak taramasına yeniden dahil etmez.

Profiller: **Hızlı** = small / batch 16 / beam 1; **Dengeli** = small / batch 8 / beam 5; **Hassas** = large-v3 / batch 8 / beam 5. Model, toplu iş boyutu, beam, GPU/CPU ve hesaplama türü ana ekrandan değiştirilebilir; değişiklik profili `Özel` yapar. Model ilk kez seçildiğinde indirilir. GPU belleği yetmezse toplu iş boyutunu 8 → 4 → 1 azaltın. Büyük batch daha çok VRAM kullanır; kullanım yüzdesinin artması tek başına daha hızlı çalıştığı anlamına gelmez. Transkript önbelleği model ve işlem ayarlarına bağlıdır; bunlar değiştiğinde video yeniden çözülür. CUDA DLL'leri PATH içinde değilse arayüzde `CUDA DLL klasörü` alanından `cublas64_12.dll` ve `cudnn64_9.dll` dosyalarını içeren klasörü seçin. Seçim hatırlanır.

**LM Studio:** Local Server'ı açın ve bir metin modeli yükleyin. Arayüzdeki IP/port alanlarına sunucunun adresini (`127.0.0.1:1234` varsayılan) yazın, **Modelleri getir** düğmesine basıp metin modelini seçin veya kimliğini elle yazın. Sunucu başka cihazdaysa yerel ağ IP adresini kullanın; LM Studio sunucusunun yerel ağ bağlantılarını kabul edecek şekilde açılması gerekir. Açık internetteki IP adresleri kabul edilmez. Transkript ve içerik tanımları bu seçili makineye gönderilir; aynı bilgisayarda tamamen yerel çalışmasını istiyorsanız `127.0.0.1` kullanın. **Thinking** alanında `Model ayarı` seçiliyse LM Studio'daki modelin kendi ayarı kullanılır; `Kapalı` seçilirse LM Studio'nun yerel `/api/v1/chat` arayüzüne `reasoning=off` gönderilir. Model bu seçeneği desteklemiyorsa hata gösterilir; uygulama gizlice thinking'i yeniden açmaz. Whisper ve LM Studio aynı GPU'yu kullanıyorsa işlem sıralıdır: önce Whisper, ardından metin modeli. Metin değerlendirmesi klasör sayısı ve video uzunluğu ile artar. Aynı dosya, Whisper ayarları, model, thinking seçimi, pencere büyüklüğü ve içerik tanımları değişmediyse sınıflandırma önbellekten okunur.

**JSON yeniden deneme:** Varsayılan değer `2`'dir; geçersiz JSON veya doğrulanamayan model cevabı gelirse aynı transkript penceresi en fazla iki kez daha sorulur (toplam en fazla üç istek). İkinci denemeden itibaren modele biçimi düzeltmesi gerektiği hatırlatılır. Sayıyı arayüzden `0–5` arasında değiştirebilirsiniz. Bağlantı hataları tekrar edilmez; son deneme de başarısız olursa video `Hata` durumunda kalır. Deneme sayısını değiştirmek başarılı sınıflandırma önbelleğini silmez. Çok sayıda tekrar istek sayısını ve analiz süresini artırabilir.

`gui.py` kaynak uygulamadır; bu pakette hazır `.exe` yoktur. Başlatıcı bir `.exe` derlemez ve ilk çalıştırmada paketleri indirir.

## Elle kurulum (isteğe bağlı)

1. Python 3.10–3.12 kurulu olsun. PowerShell'de `py -3 --version` ile kontrol edin. faster-whisper ses çözme için kendi PyAV paketini kullanır; arayüz için FFmpeg PATH gerektirmez.
2. Bu klasörde PowerShell açıp `py -3 -m venv .venv` çalıştırın.
3. `./.venv/Scripts/python.exe -m pip install -r requirements.txt` çalıştırın. CUDA kullanımı için [faster-whisper belgelerindeki](https://github.com/SYSTRAN/faster-whisper#gpu) güncel cuBLAS/cuDNN gereksinimlerini de karşılayın; kurulu değilse arayüzden CPU seçin.
4. Kural ve klasörleri arayüzde girin.

## Eski komut satırı aracı (isteğe bağlı)

Kaynak ve hedef için **ayrı klasörler** seçin. Hedef kaynak içindeyse tarama sırasında otomatik dışlanır.

```powershell
./.venv/Scripts/python.exe ayikla.py scan "D:\Videolar" "D:\AyrilanVideolar" --device cuda --model small
./.venv/Scripts/python.exe ayikla.py apply --plan-only
./.venv/Scripts/python.exe ayikla.py apply
./.venv/Scripts/python.exe ayikla.py undo
```

`scan` **dosya taşımaz**: transkriptleri `calisma_verisi/transcripts/` altında saklar, `calisma_verisi/plan.json` oluşturur. `apply --plan-only` planı ekrana basar. `apply` yalnızca bir kurala uyanları o klasöre, birden çok kurala uyanları `Incelenecekler` klasörüne taşır. Hiçbir kurala uymayanlar oldukları yerde kalır. Hedefte aynı adlı dosya varsa üzerine yazmaz. `undo`, taşıma günlüğünde kayıtlı ve değişmemiş dosyaları eski yoluna geri getirir. Aynı kaynağı tekrar tararsanız değişmemiş videonun transkripti önbellekten gelir.

`--device cpu` ile daha yavaş fakat CUDA kütüphaneleri olmadan da kullanılabilir. Model ilk kez indirilirken bağlantı gerekir. Daha doğru döküm için `--model medium` veya `--model large-v3` denenebilir; süre artar. Türkçe/İngilizce karışık seslerde önce `small` sonucunu kontrol edin.

**Sınırlar:** Komut satırı `scan` aracı eski sözcük eşleşmesi akışını kullanır; LM Studio ile anlamsal sınıflandırma yalnızca masaüstü arayüzünde çalışır. Sesi yazıya dökme hataları ve modelin yanlış yorumu sonuçları etkiler. Seslendirilmeden sadece ekranda görünen öğeler saptanamaz. Taşıma sırasında video başka programca değiştiriliyorsa aynı anda düzenlemeyin. İlk denemeyi az sayıda videonun kopyasıyla yapın.
