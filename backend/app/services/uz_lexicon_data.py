"""O'zbek tili lug'ati (lotin, 1995). Apostroflar: o' g' -> o‘ g‘ ; boshqa ' -> ’ (tutuq).

NOUNS — ot, sifat, ravish, olmosh, son va boshqa o'zgarmaydigan/otsimon so'zlar o'zaklari.
VERBS — fe'l o'zaklari (-moq siz).
CLOSED — qo'shimcha olmaydigan yordamchi so'zlar.
Lug'atni kengaytirish: data/user_lexicon.txt (har qatorda bitta so'z) yoki shu ro'yxatlar.
"""

NOUNS = """
ota ona bola farzand o'g'il qiz aka uka opa singil buva buvi bobo momo er xotin oila qarindosh do'st o'rtoq qo'shni
mehmon odam inson kishi xalq millat yigit ayol erkak qizcha keksa chaqaloq go'dak o'smir yoshlar avlod nabira kuyov kelin
amaki tog'a xola amma pochcha yanga oilaviy ota-ona ota-onasi
uy xona eshik deraza devor tom hovli ko'cha mahalla shahar qishloq tuman viloyat respublika davlat mamlakat vatan yurt joy
manzil bino maktab bog'cha universitet institut kollej texnikum litsey akademiya sinf dars darslik kitob daftar qalam ruchka
doska o'qituvchi o'quvchi talaba muallim ustoz shogird direktor rahbar boshliq xodim ishchi mutaxassis shifokor vrach hamshira
haydovchi sotuvchi dehqon fermer quruvchi muhandis olim yozuvchi shoir jurnalist muxbir boshlovchi tadbirkor biznes kompaniya
korxona tashkilot muassasa vazirlik hokimiyat hokim prezident hukumat parlament deputat senat qonun qoida tartib nizom farmon
qaror buyruq hujjat ariza shartnoma majburiyat majburiyatnoma ma'lumotnoma guvohnoma pasport imzo muhr sana vakil vakillik
vaqt soat daqiqa soniya kun tun kecha kunduz ertalab kechqurun tong oqshom hafta oy yil asr davr payt muddat zamon bugun ertaga
indin hozir endi avval keyin oldin so'ng doim hamisha har hech ba'zan tez sekin erta kech dam damlar
bahor yoz kuz qish ta'til bayram sayohat safar ekskursiya
suv non osh palov ovqat taom go'sht sut choy qahva meva sabzavot olma uzum qovun tarvuz guruch un shakar tuz yog' tuxum
hayot sog'liq salomat salomatlik kasallik dori shifoxona poliklinika davolash xavf xavfsiz xavfsizlik xatar ehtiyot
ehtiyotkor ehtiyotkorlik himoya muhofaza yordam g'amxo'rlik mas'uliyat mas'ul burch huquq erkinlik tinchlik osoyishtalik
yo'l harakat transport mashina avtomobil avtobus metro poyezd samolyot velosiped piyoda svetofor bekat chorraha trotuar
yong'in olov gaz elektr tok jihoz uskuna asbob qurilma telefon kompyuter internet sayt dastur ilova tarmoq texnologiya
sun'iy intellekt ma'lumot axborot xabar yangilik video audio rasm surat ekran
havza daryo ko'l dengiz hovuz kanal ariq tog' cho'l dala o'rmon daraxt gul o't tosh yer osmon quyosh yulduz shamol yomg'ir
qor havo issiq sovuq iqlim tabiat hayvon it mushuk qush ot sigir qo'y
ta'lim tarbiya bilim ilm fan san'at madaniyat tarix adabiyot til so'z gap jumla matn nutq ovoz tovush musiqa qo'shiq kino
film teatr sport o'yin futbol musobaqa g'alaba mag'lubiyat jamoa klub to'garak seksiya
pul so'm dollar narx savdo bozor do'kon iqtisod iqtisodiyot moliya bank soliq ish maosh daromad xarajat foyda zarar kredit
savol javob fikr g'oya maqsad niyat orzu reja loyiha natija sabab oqibat masala muammo yechim imkoniyat sharoit holat
vaziyat jarayon tajriba misol namuna qism bo'lim band modda nuqta tomon taraf soha yo'nalish daraja bosqich qadam
bosh ko'z quloq og'iz burun tish til qo'l oyoq yurak tana qon jon ruh miya yuz soch
xulq atvor xulq-atvor odob axloq mehr sevgi muhabbat do'stlik hurmat ishonch umid quvonch baxt g'am qayg'u qo'rquv
tashvish xursandchilik sabr toqat iroda
narsa buyum ish-harakat xatti-harakat faoliyat mehnat kasb hunar xizmat vazifa topshiriq lavozim
nom ism familiya yosh raqam son miqdor foiz birinchi ikkinchi uchinchi to'rtinchi beshinchi oltinchi yettinchi
bir ikki uch to'rt besh olti yetti sakkiz to'qqiz o'n yigirma o'ttiz qirq ellik oltmish yetmish sakson to'qson yuz ming
million milliard yarim chorak
men sen u biz siz ular bu shu o'sha mana ana hamma barcha butun o'z kim nima qaysi qanday qancha qayer qachon nega
nimaga negaki qanaqa shunaqa bunaqa o'zim o'zing o'zi o'zimiz o'zingiz o'zlari
yaxshi yomon katta kichik uzun qisqa yangi eski oq qora qizil ko'k yashil sariq baland past keng tor og'ir yengil oson
qiyin to'g'ri noto'g'ri muhim zarur kerak lozim shart mumkin xavfli foydali zararli go'zal chiroyli aqlli sog' kasal toza
iflos bo'sh to'la to'liq mazmun mazmunli qiziq qiziqarli bepul arzon qimmat ko'p oz kam juda eng ancha biroz butunlay qat'iy
aniq ravshan rasmiy maxsus umumiy asosiy oddiy murakkab tayyor ochiq yopiq faol jamoat ijtimoiy shaxsiy milliy xalqaro
mahalliy begona tanish notanish shaxs muloqot hudud maydon qurilish ruxsat xabardor tark mazkur qonuniy noqonuniy
quyidagi yuqoridagi tegishli boshqa yana yaqin uzoq ichki tashqi ost ust yon orqa old o'rta ich tashqari atrof
salom assalomu alaykum xayr rahmat iltimos marhamat albatta ehtimol shunday bunday mana hali allaqachon darhol tezda birga
alohida ayniqsa asosan odatda umuman masalan demak aslida rostdan rost haqiqat haqiqatan to'g'risi bo'sh vaqt
voqea hodisa holat tadbir uchrashuv yig'ilish majlis konferensiya seminar trening kurs sertifikat diplom imtihon test baho
kitobxon o'qish yozuv chizma mashq uy vazifa topshiriq olimpiada tanlov
podkast suhbat intervyu mehmon efir kanal dastur ko'rsatuv radio televizor gazeta jurnal maqola post
podshoh qahramon dushman urush g'alaba tinchlik ozodlik mustaqillik
uyqu tush nonushta tushlik kechki dam olish sayr bog' park o'yingoh stadion zal
dunyo jahon yer odamzod jamiyat hamjamiyat aholi fuqaro mehnatkash yoshlik bolalik qarilik
tashabbus ishtirok ishtirokchi a'zo guruh bo'lim kafedra fakultet rektor dekan professor dotsent
islom din masjid namoz ro'za hayit ramazon xudo alloh payg'ambar duo
nazorat tekshiruv nazoratchi hisob hisobot ro'yxat jadval grafik
sog'lom kuchli zaif tinch notinch xotirjam baxtli baxtsiz shod xafa charchoq
rost yolg'on xato xatolik kamchilik afzallik ustunlik farq o'xshash
transportda jamoatchilik zimma sifat doir rioya amal tark nazorat muhofaza tashkil ishtirok
qoidalar vasiy vasiylik domla nafar onlayn oflayn semestr muvofiq qabul avvalo o‘rin fikr aql umr shakl qadr ilm zehn
o‘zbek qozoq qirg‘iz rus ingliz tojik turkman o‘zbekcha ruscha inglizcha nafaqat balki tufayli hurmatli aziz qadrli
kurs onlayn video kamera mikrofon format fayl papka parol login akkaunt platforma tizim server model sifat tezlik
student magistr bakalavr doktor dissertatsiya grant stipendiya kontrakt yotoqxona auditoriya laboratoriya
muvaffaqiyat muvaffaqiyatsiz rivoj taraqqiyot islohot o‘zgarish yangilanish raqamli raqamlashtirish
javobgar javobgarlik majburiy ixtiyoriy talab taklif murojaat shikoyat huquqiy ijro ijrochi mavzu soat-soat qadriyat an'ana urf-odat
""".split()

VERBS = """
bor kel ket qil et ol ber qo'y tur o'tir yot yur yugur ko'r eshit gapir ayt de so'ra yoz o'qi o'rgan o'rgat bil
tushun tushuntir angla o'yla esla unut sev yoqtir xohla ist kut qara top yo'qot och yop boshla tugat bitir ishla yasha
tug'il o'l ye ich pishir yuv tozala kiy yech uxla uyg'on o'sh sot to'la yig' ajrat bo'l qo'sh chiq tush kir o'ch yon yondir
yoq quy to'k saqla ta'minla bajar foydalan qatnash tayyorla o'zgar o'zgartir oshir kamay ko'pay rivojlan rivojlantir yarat
qur ko'rsat ko'rin chiz uch suz o'yna kul yig'la qo'rq tiy taqiqla tekshir hisobla o'lcha tanla aniqla belgila yubor chaqir
uchrash yashir ko'chir o'tkaz yetkaz yet tuzat o'chir yukla kirit chiqar tushir joyla ishon ishontir tasdiqla tashla
oqla sakra tort it bos ur sur ilin qayt qaytar to'xta to'xtat davom yetish
erish ega kechir kechik shoshil tinchlan tinglа tingla eslat ogohlantir xabarla bog'la uz uzat cho'z qisqar kengay tora
ishga tashkillashtir boshqar yordamlash maslahatlash gaplash so'zlash suhbatlash yozish tarbiyala o'stir o'sib
o'qit o'qil yozil qilin ber bera berish ko'zla kuzat qo'lla qo'llab-quvvatla quvvatla mustahkamla sog'in sog'ay
og'ri og'rit davola charcha dam_ol hayajonlan xursand tabrikla sevin quvon kuyin achin yoqol yo'qol
tanish tanishtir sina tamomla tamomlan kengay kengaytir tingla tinglan ishlat ishla foydalan mos tushir tushun gapir so‘zla izla qidir yuklab
""".replace("dam_ol", "").replace("tinglа", "").split()

CLOSED = """
va hamda yoki yo balki ham faqat hatto xuddi kabi singari uchun bilan orqali haqida to'g'risida bo'yicha sari qarshi
lekin ammo biroq chunki agar garchi toki modomiki emas yo'q bor ha xo'p mana ana go'yo sababli tufayli deb degan
endi hali yana ham-da hatto-ki ko'ra nisbatan qadar gacha beri buyon so'ng keyin oldin avval esa-da esa
1995 bu u shu o'sha
""".split()

# Ko'p uchraydigan to'liq so'z shakllari (morfologiya qamrab olmagan holatlar uchun)
FORMS = """
uni uning unga unda undan ularni ularning ularga ularda ulardan bular bularni shular shuni shuning shunga shunda shundan bunga bunda bundan buni buning menga meni mening mendan menda senga seni sening bizga bizni bizning sizga sizni sizning kimga kimni kimning nimaga nimani nimaning
ehtiyotkor ehtiyotkorlik xavfsizligini salomatligini hayotini farzandimning o'quvchining o'quvchisining ota-onasining
ta'minlash to'g'risida sifatida quyidagi yuqoridagi davomida davrida mazmunli muloqotda zimmamga anglagan holda
qilmasdan bormaslik etmaslik qilish bo'lish
""".split()
