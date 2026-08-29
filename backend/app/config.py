from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    backend_host: str = "127.0.0.1"
    backend_port: int = 8000

    frontend_origin: str = "http://localhost:5173"

    # 本地登录态有效期（秒）。暂时关闭过期：0 = 不限时（原值 30*60，需要时恢复注释即可）
    # cookie_ttl_seconds: int = 30 * 60
    cookie_ttl_seconds: int = 0
    cookie_store_dir: Path = Path(__file__).resolve().parent.parent / "data" / "cookies"

    session_ttl_seconds: int = 30 * 60

    # 统一身份认证 CAS（真实地址，来源：Kelab/auth_swust、YDHusky/SWUST-Tools）
    swust_cas_base_url: str = "https://cas.swust.edu.cn/authserver"
    swust_cas_login_url: str = "https://cas.swust.edu.cn/authserver/login"
    swust_cas_captcha_url: str = "https://cas.swust.edu.cn/authserver/captcha"
    swust_cas_getkey_url: str = "https://cas.swust.edu.cn/authserver/getKey"
    swust_cas_callback_url: str = "https://cas.swust.edu.cn/authserver/callback"

    # 教务系统（真实地址，CFM 老系统）
    swust_dean_base_url: str = "https://matrix.dean.swust.edu.cn/acadmicManager/index.cfm"
    swust_dean_portal_event: str = "studentPortal:DEFAULT_EVENT"
    swust_dean_coursetable_event: str = "studentPortal:courseTable"

    # 门户
    swust_portal_service_url: str = "https://soa.swust.edu.cn/sys/portal/page.jsp"
    swust_student_info_url: str = "http://myo.swust.edu.cn/mht_shall/a/service/studentInfo"

    # 微信扫码（真实 appid，来源：YDHusky/SWUST-Tools/wx_login_test.py）
    wx_open_appid: str = "wx3e5a3c590b52de4d"
    wx_qrconnect_url: str = "https://open.weixin.qq.com/connect/qrconnect"
    wx_qrconnect_poll_url: str = "https://open.weixin.qq.com/connect/l/qrconnect"
    wx_open_base: str = "https://open.weixin.qq.com"

    swust_qrcode_poll_interval: float = 1.5
    swust_qrcode_timeout: int = 120

    # 登录态 httpx cookie jar 持久化路径（--reload/重启后恢复，避免重新扫码）
    auth_jar_path: Path = Path(__file__).resolve().parent.parent / "data" / "auth_jar.json"

    # 教学班详情并行抓取。实测教务系统（老 CFM）对同一 session 的请求近似串行加锁，
    # 并发过高只会加深排队、触发超时重试，反而更慢；6 并发 + 30s 超时实测稳定。
    fetch_concurrency: int = 6
    fetch_max_attempts: int = 3
    fetch_retry_delay: float = 0.6
    fetch_detail_timeout: float = 30.0

    http_timeout: float = 15.0
    http_max_retries: int = 3

    login_poll_interval: float = 1.5
    login_timeout: int = 120

    # 选课轮次 CT（需按当前学期实际选课轮次调整）
    choose_course_ct: int = 2


settings = Settings()
settings.cookie_store_dir.mkdir(parents=True, exist_ok=True)
