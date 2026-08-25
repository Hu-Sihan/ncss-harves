from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .areas import AREA_CODES, PROVINCE_AREA_CODES
from .errors import InvalidFilter
from .models import Query

JOB_CATEGORY_CODES = {
    "计算机/网络/技术类": "01", "电子/电器/通信技术类": "02", "行政/后勤类": "03",
    "翻译类": "04", "销售类": "05", "客户服务类": "06", "市场/公关/媒介类": "07",
    "咨询/顾问类": "08", "财务/审计/统计类": "09", "人力资源类": "10",
    "教育/培训类": "11", "质量管理类": "12", "美术/设计/创意类": "13",
    "技工类": "14", "金融保险类": "15", "贸易/物流/采购/运输类": "16",
    "经营管理类": "17", "商业零售类": "18", "建筑/房地产/装饰装修/物业管理类": "19",
    "法律类": "20", "酒店/餐饮/旅游/服务类": "21", "生物/制药/化工/环保类": "22",
    "文体/影视/写作/媒体类": "23", "机械/仪器仪表类": "24", "科研类": "25",
    "工厂生产类": "26", "医疗卫生/美容保健类": "27", "电气/能源/动力类": "28",
    "其他类": "29",
}

INDUSTRY_CODES = {
    "互联网/通信/电子": "0001", "金融": "0002", "生产/加工/制造": "0003",
    "制药/医疗": "0004", "广告/传媒/文化/体育": "0005", "教育": "0006",
    "房地产/建筑业": "0007", "贸易/工艺/消费品": "0008", "能源/矿产": "0009",
    "物流/运输": "0010", "服务业": "0011", "政府/非营利机构/其他": "0012",
}

INDUSTRY_DETAIL_CODES = {
    "计算机软件": "000101", "计算机硬件": "000102", "计算机服务（系统/数据/维护/安全）": "000103",
    "互联网/电子商务": "000104", "网络游戏": "000105", "通信/电信设备、运营、增值服务": "000106",
    "通信技术开发及应用": "000108", "电子技术/半导体/集成电路": "000109",
    "投资/基金/证券/期货": "000201", "保险": "000202", "银行": "000203",
    "信托/担保/拍卖/典当": "000204", "财会/审计": "000205",
    "机械制造/机电/重工": "000301", "航空/航天研究与制造": "000302",
    "仪器/仪表/工业自动化/电气": "000303", "汽车/摩托车（制造/维护/配件/销售/服务）": "000304",
    "原材料及加工（金属/木材/橡胶/塑料/玻璃/陶瓷/建材）": "000305",
    "印刷/包装/造纸": "000306", "办公设备及用品": "000307",
    "医疗/护理/卫生服务": "000401", "制药/生物工程": "000402", "医疗设备/器械": "000403",
    "广告/公关/会展": "000501", "媒体/出版/影视/文化传播": "000502",
    "娱乐/体育/休闲": "000503", "市场推广/运营": "000504", "艺术设计": "000505",
    "教育/培训/院校": "000601", "学术/科研": "000602",
    "房地产/建筑/建材/工程": "000701", "家居/室内设计/装饰装潢": "000702",
    "物业管理/商业中心": "000703", "贸易/进出口": "000801", "家电业": "000802",
    "批发/零售": "000803", "礼品/玩具/工艺美术/珠宝": "000804",
    "收藏品/奢侈品": "000805", "快速消费品（食品/饮料/日化/烟酒）": "000806",
    "耐用消费品（服饰/纺织/皮革/家具）": "000807", "能源/矿产采掘/冶炼": "000901",
    "石油/石化/化工": "000902", "电气/电力/水利": "000903", "新能源": "000904",
    "物流/仓储": "001001", "交通/运输": "001002",
    "专业服务（财会/法律/翻译/人力资源等）": "001101", "检验/检测/认证": "001102",
    "租赁服务": "001103", "中介服务": "001104", "外包服务": "001105",
    "美容/保健": "001106", "酒店/餐饮": "001107", "旅游/度假": "001108",
    "政府/公共事业/非盈利机构": "001201", "环保": "001202", "农/林/牧/渔": "001203",
    "综合领域经营": "001204", "其他": "001205",
}

PROPERTY_VALUES = (
    "国有企业", "股份制企业", "民营企业", "上市公司", "港澳台公司", "合资企业",
    "外商独资/外企代表处", "机关/事业单位/非营利机构", "其他",
)
JOB_TYPE_VALUES = {"工作": "全职", "全职": "全职", "兼职": "兼职", "实习": "实习"}
CRAWL_JOB_TYPE_VALUES = ("全职", "兼职", "实习")
DEGREE_VALUES = ("大专", "本科", "硕士", "博士")
DEGREE_NATIVE_VALUES = {"大专": "41", "本科": "31", "硕士": "11", "博士": "01"}
COMPANY_TYPE_VALUES = ("重点领域", "精选企业")
RECRUIT_TYPE_VALUES = ("职位", "公告")
MONTH_PAY_NATIVE_VALUES = {
    "2K以下": "2",
    "2K-5K": "2-5",
    "5K-10K": "5-10",
    "10K-15K": "10-15",
    "15K-25K": "15-25",
    "25K-50K": "25-50",
    "50K以上": "50",
    "面议": "0",
}
SOURCE_VALUES = (
    "国家大学生就业服务平台", "省市及高校", "BOSS直聘", "中华英才网", "猎聘", "全联人才在线",
    "前程无忧", "智联招聘", "实习僧", "国聘", "一览英才网", "中国中小企业信息网",
    "中智招聘", "Beisen北森", "丁香人才", "易展翅", "北极星招聘",
)

SOURCE_NATIVE_VALUES = {
    "国家大学生就业服务平台": ("0", ""), "省市及高校": ("", "1"),
    "BOSS直聘": ("2000846399", "0"),
    "中华英才网": ("sx4tfd53g3drg3lhcabun0cjmylq8jan", "0"),
    "猎聘": ("2000846397", "0"),
    "全联人才在线": ("wppuiz6fu2k6pi030gvd45l8wky8l1ex", "0"),
    "前程无忧": ("19etdf5giehhg58vzrf5m0en8hldvkvw", "0"),
    "智联招聘": ("fawzqa3wo3hy2x4uqe1b1bwy4met2wpb", "0"),
    "实习僧": ("2xy7zytm7pt75iz09glwxs5554t621uf", "0"),
    "国聘": ("gn5yn9s9wjydmrlh5kre1rzkma8mmjbu", "0"),
    "一览英才网": ("bbqeda1p0l0fkoinaywn8yra176xrz2l", "0"),
    "中国中小企业信息网": ("2000846398", "0"),
    "中智招聘": ("xrtjvzrkqlm0n2wo0nrh74dyo2kij9sm", "0"),
    "Beisen北森": ("1zl8wkl8ixb1e1c1095fmdtrzwzegltk", "0"),
    "丁香人才": ("rjrwyk6f2n6snh2c6fdz7dwfd6852gmb", "0"),
    "易展翅": ("1fgc34ei0xf5ure5ce82cxtwz4ovq6gf", "0"),
    "北极星招聘": ("mfd56jlomqoq2efagv04o9i6cn0krhvl", "0"),
}

RANDOM_FILTER_VALUE = "random"


NativeItems = tuple[tuple[str, str], ...]
NativeOption = NativeItems


@dataclass(frozen=True, slots=True)
class CrawlRequest:
    common_items: NativeItems = ()
    dimensions: tuple[tuple[NativeOption, ...], ...] = ()
    page: int = 1
    limit: int = 20

    def native_params(
        self,
        combination: tuple[NativeOption, ...] = (),
        *,
        limit: int | None = None,
    ) -> dict[str, object]:
        native = dict(self.common_items)
        for option in combination:
            native.update(option)
        return {
            "jobName": "",
            "offset": self.page,
            "limit": self.limit if limit is None else limit,
            **native,
        }


def split_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    raw_values = value if isinstance(value, (list, tuple, set)) else (value,)
    flattened = (
        part.strip()
        for item in raw_values
        for part in str(item).replace("，", ",").split(",")
    )
    return tuple(dict.fromkeys(part for part in flattened if part))


def _validated(value: object, allowed: tuple[str, ...], dimension: str) -> tuple[str, ...]:
    values = split_values(value)
    if not values or any(item in {"全部", "不限"} for item in values):
        return ()
    for item in values:
        if item not in allowed:
            raise InvalidFilter(dimension, item, ("全部", *allowed))
    return values


def _crawl_values(
    value: object,
    allowed: tuple[str, ...],
    dimension: str,
) -> tuple[str, ...]:
    values = split_values(value)
    if RANDOM_FILTER_VALUE in values:
        return allowed
    if not values or any(item in {"全部", "不限"} for item in values):
        return ()
    for item in values:
        if item not in allowed:
            raise InvalidFilter(
                dimension,
                item,
                ("全部", RANDOM_FILTER_VALUE, *allowed),
            )
    return values


def _crawl_area_values(value: object) -> tuple[str, ...]:
    values = split_values(value)
    if RANDOM_FILTER_VALUE in values:
        return tuple(PROVINCE_AREA_CODES)
    return _crawl_values(value, tuple(AREA_CODES), "areaName")


def _job_types(value: object) -> tuple[str, ...]:
    values = split_values(value)
    if not values or any(item in {"全部", "不限"} for item in values):
        return ()
    result: list[str] = []
    for item in values:
        if item not in JOB_TYPE_VALUES:
            raise InvalidFilter("jobType", item, ("全部", *JOB_TYPE_VALUES))
        normalized = JOB_TYPE_VALUES[item]
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


def _crawl_job_types(value: object) -> tuple[str, ...]:
    values = split_values(value)
    if RANDOM_FILTER_VALUE in values:
        return CRAWL_JOB_TYPE_VALUES
    if not values or any(item in {"全部", "不限"} for item in values):
        return ()
    result: list[str] = []
    for item in values:
        if item not in JOB_TYPE_VALUES:
            raise InvalidFilter(
                "jobType",
                item,
                ("全部", RANDOM_FILTER_VALUE, *JOB_TYPE_VALUES),
            )
        normalized = JOB_TYPE_VALUES[item]
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


def _integer(value: object, default: int, minimum: int, maximum: int, name: str) -> int:
    try:
        result = default if value in (None, "") else int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


def _boolean(value: object, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError("invalid boolean")


def query_from_params(params: Mapping[str, object]) -> Query:
    industries = (*INDUSTRY_CODES, *INDUSTRY_DETAIL_CODES)
    return Query(
        job_name=str(params.get("jobName") or "").strip(),
        area_names=_validated(params.get("areaName"), tuple(AREA_CODES), "areaName"),
        degree_names=_validated(params.get("degreeName"), DEGREE_VALUES, "degreeName"),
        category_names=_validated(params.get("categoryName"), tuple(JOB_CATEGORY_CODES), "categoryName"),
        industry_names=_validated(params.get("industrySectors"), industries, "industrySectors"),
        job_types=_job_types(params.get("jobType")),
        properties=_validated(params.get("property"), PROPERTY_VALUES, "property"),
        company_types=_validated(params.get("companyType"), COMPANY_TYPE_VALUES, "companyType"),
        month_pay=str(params.get("monthPay") or "").strip(),
        recruit_types=_validated(params.get("recruitType"), RECRUIT_TYPE_VALUES, "recruitType"),
        source_names=_validated(params.get("sourceName"), SOURCE_VALUES, "sourceName"),
        publish_date_from=str(params.get("publishDateFrom") or "").strip(),
        publish_date_to=str(params.get("publishDateTo") or "").strip(),
        random=_boolean(params.get("random")),
        page=_integer(params.get("offset"), 1, 1, 2_147_483_647, "offset"),
        limit=_integer(params.get("limit"), 20, 1, 100, "limit"),
    )


def crawl_request_from_params(params: Mapping[str, object]) -> CrawlRequest:
    for name in ("publishDateFrom", "publishDateTo", "random"):
        if name in params:
            raise ValueError(f"{name} is only supported by /query")

    common: dict[str, str] = {}
    dimensions: list[tuple[NativeOption, ...]] = []
    job_name = str(params.get("jobName") or "").strip()
    if job_name:
        common["jobName"] = job_name

    month_pay_dimension: tuple[NativeOption, ...] = ()
    month_pay_values = split_values(params.get("monthPay"))
    if RANDOM_FILTER_VALUE in month_pay_values:
        month_pay_dimension = tuple(
            (("monthPay", native),)
            for native in MONTH_PAY_NATIVE_VALUES.values()
        )
    elif month_pay_values and not any(
        value in {"全部", "不限"} for value in month_pay_values
    ):
        invalid_month_pay_values = tuple(
            value
            for value in month_pay_values
            if value not in MONTH_PAY_NATIVE_VALUES
        )
        if invalid_month_pay_values:
            raise InvalidFilter(
                "monthPay",
                ",".join(invalid_month_pay_values),
                ("全部", RANDOM_FILTER_VALUE, *MONTH_PAY_NATIVE_VALUES),
            )
        if len(month_pay_values) == 1:
            common["monthPay"] = MONTH_PAY_NATIVE_VALUES[month_pay_values[0]]
        else:
            month_pay_dimension = tuple(
                (("monthPay", MONTH_PAY_NATIVE_VALUES[value]),)
                for value in month_pay_values
            )

    areas = _crawl_area_values(params.get("areaName"))
    if areas:
        dimensions.append(
            tuple((("areaCode", AREA_CODES[value]),) for value in areas)
        )

    job_types = _crawl_job_types(params.get("jobType"))
    if job_types:
        native_job_types = {"全职": "01", "兼职": "02", "实习": "03"}
        dimensions.append(
            tuple((("jobType", native_job_types[value]),) for value in job_types)
        )

    company_types = _crawl_values(
        params.get("companyType"), COMPANY_TYPE_VALUES, "companyType"
    )
    if company_types:
        native_company_types = {
            "重点领域": (("keyUnits", "1"),),
            "精选企业": (("memberLevel", "2"),),
        }
        dimensions.append(tuple(native_company_types[value] for value in company_types))

    degrees = _crawl_values(params.get("degreeName"), DEGREE_VALUES, "degreeName")
    if degrees:
        dimensions.append(
            tuple((("degreeCode", DEGREE_NATIVE_VALUES[value]),) for value in degrees)
        )
    if month_pay_dimension:
        dimensions.append(month_pay_dimension)

    categories = _validated(params.get("categoryName"), tuple(JOB_CATEGORY_CODES), "categoryName")
    if categories:
        dimensions.append(
            tuple((("categoryCode", JOB_CATEGORY_CODES[value]),) for value in categories)
        )

    industry_labels = _validated(
        params.get("industrySectors"),
        (*INDUSTRY_CODES, *INDUSTRY_DETAIL_CODES),
        "industrySectors",
    )
    industry_options: list[NativeOption] = []
    for label in industry_labels:
        if label in INDUSTRY_DETAIL_CODES:
            native_value = f"{INDUSTRY_DETAIL_CODES[label]},"
        else:
            prefix = INDUSTRY_CODES[label]
            codes = tuple(
                code for code in INDUSTRY_DETAIL_CODES.values() if code.startswith(prefix)
            )
            native_value = f"{','.join(codes)},"
        industry_options.append((("industrySectors", native_value),))
    if industry_options:
        dimensions.append(tuple(industry_options))

    properties = _crawl_values(params.get("property"), PROPERTY_VALUES, "property")
    if properties:
        dimensions.append(tuple((("property", value),) for value in properties))

    recruit_types = _crawl_values(
        params.get("recruitType"), RECRUIT_TYPE_VALUES, "recruitType"
    )
    if recruit_types:
        native_recruit_types = {"职位": "0", "公告": "1"}
        dimensions.append(
            tuple(
                (("recruitType", native_recruit_types[value]),)
                for value in recruit_types
            )
        )

    source_names = _crawl_values(params.get("sourceName"), SOURCE_VALUES, "sourceName")
    source_options: list[NativeOption] = []
    for source_name in source_names:
        code, source_type = SOURCE_NATIVE_VALUES[source_name]
        option: list[tuple[str, str]] = []
        if code:
            option.append(("sourcesName", code))
        if source_type:
            option.append(("sourcesType", source_type))
        source_options.append(tuple(option))
    if source_options:
        dimensions.append(tuple(source_options))

    return CrawlRequest(
        common_items=tuple(common.items()),
        dimensions=tuple(dimensions),
        page=_integer(params.get("offset"), 1, 1, 50, "offset"),
        limit=_integer(params.get("limit"), 20, 1, 100, "limit"),
    )
