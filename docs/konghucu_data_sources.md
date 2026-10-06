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

## 自己抓取的工作流（`konghucu/` 模块）

决定不走申请，自己收集公开汇总数据。三条管道并行，最后合并：

1. **BPS Web API**（主干，可回溯）。在 https://webapi.bps.go.id 免费注册拿 key，`bps-search` 在 38 个省域里按关键词 "agama" 列出静态表，筛出标题含 kabupaten/kota 的，`bps-fetch` 下载 HTML 表并解析成长表。BPS 省级年鉴表的来源多为 Kemenag 或 Dukcapil，表头会写，记录在 `ref` 里。
2. **GIS Dukcapil ArcGIS REST**（当前期，全国一致口径）。`arcgis-discover` 遍历服务目录找含宗教字段的图层；公开图层直接 `arcgis-fetch` 分页拉全表，返回 498/499 的是需要 token 的，跳过不绕。
3. **县级 Dukcapil PDF**（补缺与核对）。各县半年一份的 Data Agregat PDF 用 `pdf-extract` 抽表，格式各异，抽出来必须抽样对照原文。

`harmonize` 用 BPS 县代码表把名字对到 4 位代码，打印对不上的名字让你手工补，然后生成 unit × year × semester 面板。区划拆分（pemekaran）不在这里处理，拿到面板后用明确的 crosswalk 合并。

实际运行只能在本地做：这个云容器的网络策略拦掉了 bps.go.id、data.go.id 和 kemendagri.go.id，代码只经过离线测试（`tests/test_konghucu.py`），第一次跑真实接口时留意 BPS 返回的 JSON 结构是否与 `bps_api.py` 的假设一致。

## 已知的脏表

- `bps:3300:1881`（中爪哇 2019 到 2021 三年表）：原始 HTML 里 Cilacap 等县的穆斯林人数三年完全相同，天主教 2021 列是 16 这种明显错位的值。BPS 自己的表就是这样。`harmonize.build_panel` 的来源优先级把动态表（bpsvar）和单年静态表排在前面，这张表只在没有别的来源时才会被用到。
- `bps:6400:321`（东加里曼丹 2015，Kemenag 口径）：Samarinda 孔教 32,001 人，比任何其他来源高一个数量级，原表如此。已列入排除名单。
- 北苏门答腊 Sibolga（1271）：`bps:1200:2793`（2021）给的穆斯林人数 155,207 几乎等于同表 Tapanuli Tengah 的 155,188，佛教 15,078 也不对，合计 185,939 超过全市人口（约 9 万）；`bpsvar:1200:804`（2025）给的天主教 99,747 同样超过全市人口。用 `bps-inspect --raw-rows` 核对过，原始单元格就是这些数，不是解析错位。这类单格错误不能整表排除，列在 `konghucu/drop_cells.csv`（unit_code, year, ref, reason，前三个字段任选，设了的字段都要匹配：unit_code+year 去掉一个县年，ref 去掉整张表，ref+year 去掉动态表的某一年），`harmonize` 默认读取并剔除。
- 同类问题的筛法：`harmonize` 会把 total 偏离该县各年中位数 35% 以上的县年列出并写到 `total_outliers.csv`。一个县几年内不会多出或少掉三分之一人口，这种基本都是某个宗教抄错了行。核对原始单元格后加进 `drop_cells.csv`。面板每个县年的所有宗教都来自同一张表（`ref` 列），不会把两张表的宗教拼在一起。
- 东爪哇、日惹大多数县级表没有孔教列，孔教并在 Lainnya 里。这些县只能把 Lainnya 当上界。
- 县级表的总计行标签不统一（Jumlah、县名、年份、或没有），识别顺序是：Jumlah 标签，等于其他行之和，县名且明显最大，最后加总 kecamatan（source 记为 bps_kabsum）。

## 官方人口作为锚

`bps-population` 在每个省域里找标题是"Jumlah Penduduk Menurut Kabupaten/Kota"一类的动态变量（排除按性别、年龄、贫困、kecamatan 分的），抓全部年份，同一县年若有几个序列取中位数，输出 `data/konghucu/population.csv`（unit_code, year, population, n_refs, spread）。`harmonize` 默认读取它，面板里加 `population`、`total_to_pop`、`konghucu_share_pop`。

用途有两个。一是孔教占比的分母用官方人口而不是宗教表各列之和，宗教表少一列或多抄一行不会传到分母里。二是离群值判断用官方人口做锚而不是该县各年的中位数：Buton（7401）2014 年拆出两个新县后人口减半，按中位数会被当成错误，按当年人口则正常；反过来苏拉威西北那张 Kemenag 序列各年在真实人口的 0.2 到 2 倍之间乱跳，按中位数只能抓到一半。

面板构建时还会按格子自身的值丢掉明显不是人数的格子（`quality` 列）：各宗教加起来约等于 100 的是百分比表；四个以上宗教数值完全相同的是占位符；只有合计没有分宗教的没法用；缺 Islam、Kristen、Katolik 任一列的，合计设为缺失（`partial`），宗教人数本身保留。来源报告的合计若与各宗教之和相差 10% 以上，用各宗教之和（`total_reported` 保留原值）。

## 两套口径：Kemenag 与 Dukcapil

同一个县的孔教人数在不同年份的表里可以差几十倍，不是解析错误。北苏门答腊的例子：Medan 在 2020 和 2022 的 "Jumlah Umat Agama" 表里是 11,194，在 2021 的 "Penduduk Menurut Agama yang Dianut" 表和 2025 动态表里是 285 和 406。前者是宗教部（Kemenag）按宗教组织申报统计的信众，后者是人口登记局（Dukcapil）按身份证宗教栏统计的登记人口。研究设计里"改身份证宗教为孔教"这个有成本的行为对应的是 Dukcapil 口径。

面板里 `konghucu_ref` 标明每个值来自哪张表；`harmonize` 会把相邻年份跳 5 倍以上的县年列出并写到 `konghucu_breaks.csv`。做面板回归前要按口径分开，或只用一种口径的年份。BPS 表的标题通常不写来源，判断方法：看该表的 `Sumber` 脚注（原始 HTML 最后几行），或比较同一县在两张表里的倍数关系。
