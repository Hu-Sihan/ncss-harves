from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PACKAGE_ROOT / "data"
DATABASE_PATH = DATA_DIR / "ncss.db"
CREDENTIAL_PATH = DATA_DIR / "ncss-credentials.key"
CHROME_PROFILE_DIR = DATA_DIR / "chrome-profile"

WORK_URL = "https://www.ncss.cn/student/jobs/index.html"
INTERNSHIP_URL = "https://www.ncss.cn/student/jobs/internindex.html"
LIST_URL = "https://www.ncss.cn/student/jobs/jobslist/ajax/"
DETAIL_URL = "https://www.ncss.cn/student/jobs/{job_id}/detail.html"
PERSON_CENTER_URL = "https://www.ncss.cn/student/resume/personcenter.html"
LOGIN_URL = (
    "https://account.chsi.com.cn/passport/login"
    "?service=https://www.ncss.cn/student/connect/chsi&entrytype=stu"
)

REQUEST_TIMEOUT_SECONDS = 10.0
REQUEST_RETRY_WAIT_SECONDS = 5.0
INITIAL_PAGE_COUNT = 50
NCSS_PAGE_SIZE = 20
