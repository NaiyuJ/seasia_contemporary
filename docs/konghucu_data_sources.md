# 孔教（Khonghucu）登记人口：数据来源

## 背景

- 1967 年 Inpres 14 限制华人宗教文化活动；2000 年 Keppres 6 废止；2006 年人口行政法（UU 23/2006）后身份证宗教栏可以填 Khonghucu。所以这个指标有意义的起点大约是 2006 到 2010 年。
- 2000 年人口普查把孔教归入"其他"；2010 年普查单列。

## 来源，按优先级

1. **Dukcapil Kemendagri，DKB（Data Kependudukan Bersih）半年数据**
   - 每年 6 月 30 日和 12 月 31 日各发布一次，全国、省、县三级，含宗教分项。
   - 入口：https://dukcapil.kemendagri.go.id/page/read/data-kependudukan 。全国汇总常以 PDF 或新闻稿形式发布；县级表散落在各省、各县 Dukcapil 网站的 "Data Agregat Kependudukan" 页面，例如西加里曼丹省 https://dukcapil.kalbarprov.go.id/data/data-agregat-kependudukan 。
   - 完整的县级面板通常要向 Ditjen Dukcapil 提交数据利用申请（pemanfaatan data），学术用途可以申请。
2. **GIS Dukcapil** https://gis.dukcapil.kemendagri.go.id/peta/ ：按省、县的地图层，含宗教分项，可以抓取当前期数据，历史期不一定保留。
3. **Satu Data Indonesia** https://data.go.id 和各省市开放数据门户：搜 "jumlah penduduk menurut agama"，有些县公布到 kecamatan 或 kelurahan 级，例如 Bantul 的 Konghucu 按 kalurahan 数据 https://katalog.data.go.id/dataset/jumlah-penduduk-menganut-agama-konghucu-menurut-kalurahan 。覆盖不均，适合补细粒度，不适合做全国面板。
4. **BPS**：2010 年普查（SP2010）按县的宗教表；各省 BPS 网站的统计表（来源多为 Kemenag 或 Dukcapil），例如北苏门答腊 2020 年县级宗教表 https://sumut.bps.go.id/en/statistics-table/1/MjI4OSMx/jumlah-penduduk-menurut-kabupaten-kota-dan-agama-yang-dianut-2020.html 。各省 "Provinsi Dalam Angka" 年鉴里也有按县的宗教表，可以回溯到 2010 年代初。
5. **IPUMS International**：2010 年普查 10% 微观样本，同时有族群（suku）和宗教，可以算每个县"华裔中登记为孔教的比例"作为基期。这是唯一能把族群和宗教交叉的来源。
6. **Kemenag（宗教事务部）**：Data Umat Beragama，省级为主。

## 注意

- Dukcapil 和 BPS 的口径不同：Dukcapil 是登记人口（de jure，按身份证），BPS 普查是常住人口。做面板要固定用一个来源。
- 县的行政区划在 2000 年代有大量拆分（pemekaran），要用 BPS 的区划对照表把老县合并回去。
- 分母用该县华裔人口（2010 普查）而不是总人口，否则指标主要反映华裔人口的分布。
- 改宗记录的是身份证上的变化，背后可能是孔教组织（Matakin）的地方动员，而不仅是个人选择。把 Matakin 分会的设立时间也收集进来做控制。
