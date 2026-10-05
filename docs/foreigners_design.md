# 外籍人口（含中国籍）按县：测量说明

## 为什么需要

街景汉字、孔教登记、华人企业对华贸易这些结果变量，都会被中国籍人员的在地存在污染。中资进入带来的劳工和管理人员会抬高中文招牌、也可能出现在人口登记里。需要一个独立于华人社群的"中国籍存在"指标，用来控制、剔除或构造安慰剂。

## 公开到什么程度

- 移民局不发按县、按国籍的居留许可表。全国层面只有新闻稿里的总数。
- BPS 各省年鉴有 "Jumlah Orang Asing Menurut Kebangsaan dan Permohonan Izin Tinggal"，来源是辖区内各移民局（Kanim）。有的省按 Kanim 分列，有的只有省合计。一个 Kanim 管几个县。
- Kemnaker 的外籍劳工（TKA）按来源国：全国有，部分省级开放数据门户有，个别省到县。只覆盖持工作许可的人。
- Dukcapil DKB 的 WNI/WNA 分项：县级 PDF 里常见，但 WNA 只算持永居（KITAP）并领了 KTP-el 的人，产业园劳工不在内。
- 人口普查 2010、2020 有按县的外籍人口，不分国籍，可做基期。

## 模块做什么

`foreigners/` 把四类来源抓成一张长表：source、province_code、region_name、region_level（province / kanim / kabupaten / kecamatan）、nationality（ISO3 式代码，中国大陆 CHN，台湾 TWN，香港 HKG）、permit_type（ITAS / ITAP / ITK / TKA / RESIDENT）、year、count、ref。

`harmonize` 把 Kanim 行按用户提供的对照表分摊到县（可带权重，默认等分），县级行按名字对 BPS 代码，省级行保留为省 × 年的上下文列。面板输出 `chn_itas`、`chn_tka`、`chn_any`、`wna_resident`、`foreign_total`、`chn_province_any`。

## 识别上的注意

1. **Kanim 分摊是人为的。** 等分或按人口分摊都不反映外国人的真实分布。用这个变量做剔除（"剔除 Kanim 辖区内有大量中国籍的县"）比做连续控制更稳妥。
2. **三个来源口径互不兼容。** ITAS 是存量许可，TKA 是工作许可，WNA 是永居登记。不要相加，分别放进回归，或只选一个做主控制。
3. **中国籍与华人不可能从这些表里区分**：WNA 里也有台湾、香港籍的老华人家庭。TWN、HKG 单独保留。
4. **年份对齐。** BPS 年鉴表的年份是出版年减一，`year_from_text` 取标题里最后一个年份，抓完要抽查几张表核对。
