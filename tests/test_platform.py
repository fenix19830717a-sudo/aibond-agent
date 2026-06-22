"""
aibond 平台前端 Playwright 测试

测试目标平台: https://aib2b.bond
技术栈: React + Ant Design
认证方式: JWT (POST /api/auth/login)

运行方式:
    pip install playwright pytest-playwright
    playwright install chromium
    pytest tests/test_platform.py -v

配置:
    设置环境变量:
        AIBOND_TEST_URL=https://aib2b.bond
        AIBOND_TEST_USERNAME=your_username
        AIBOND_TEST_PASSWORD=your_password
"""

import os
import re
import pytest
from playwright.sync_api import Page, expect


BASE_URL = os.environ.get("AIBOND_TEST_URL", "https://aib2b.bond")
ADMIN_USERNAME = os.environ.get("AIBOND_TEST_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("AIBOND_TEST_PASSWORD", "admin123")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def auth_token(page: Page):
    """通过浏览器 API 请求登录，获取 JWT token。"""
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, f"登录失败: {response.status} {response.text}"
    body = response.json()
    token = body.get("token")
    assert token, f"登录响应中未找到 token: {body}"
    return token


@pytest.fixture(scope="function")
def auth_headers(auth_token):
    """构造 Authorization 请求头。"""
    return {"Authorization": f"Bearer {auth_token}"}


# ---------------------------------------------------------------------------
# 1. Health Check
# ---------------------------------------------------------------------------


def test_health_endpoint_returns_200(page: Page):
    """GET /api/health 返回 200 且 status 为 ok。"""
    response = page.request.get(f"{BASE_URL}/api/health")
    assert response.status == 200, f"期望 200, 实际 {response.status}"
    body = response.json()
    assert body.get("status") == "ok", f"期望 status=ok, 实际 {body}"


# ---------------------------------------------------------------------------
# 2. Authentication
# ---------------------------------------------------------------------------


def test_login_page_loads(page: Page):
    """/login 页面加载后应显示密码输入框。"""
    page.goto(f"{BASE_URL}/login")
    page.wait_for_load_state("networkidle")

    password_input = page.locator('input[type="password"]').first
    expect(password_input).to_be_visible(timeout=10000)


def test_login_with_valid_credentials(page: Page):
    """使用有效凭据登录后应重定向到主页面。"""
    page.goto(f"{BASE_URL}/login")
    page.wait_for_load_state("networkidle")

    # 填写用户名
    username_input = page.locator('input[placeholder*="用户名"], input[id*="user"], input[name*="user"]').first
    if username_input.is_visible():
        username_input.fill(ADMIN_USERNAME)
    else:
        page.locator("input[type='text'], input:not([type])").first.fill(ADMIN_USERNAME)

    # 填写密码
    page.locator("input[type='password']").first.fill(ADMIN_PASSWORD)

    # 点击登录按钮
    page.locator('button:has-text("登录"), button[type="submit"]').first.click()

    # 等待导航完成
    page.wait_for_url(re.compile(rf"^{re.escape(BASE_URL)}/(?!login).*$"), timeout=15000)
    current_url = page.url
    assert "/login" not in current_url, f"登录后未跳转, 当前 URL: {current_url}"


def test_login_with_invalid_credentials_shows_error(page: Page):
    """使用错误密码登录应显示错误提示或停留在登录页。"""
    page.goto(f"{BASE_URL}/login")
    page.wait_for_load_state("networkidle")

    # 填写用户名
    username_input = page.locator('input[placeholder*="用户名"], input[id*="user"], input[name*="user"]').first
    if username_input.is_visible():
        username_input.fill(ADMIN_USERNAME)
    else:
        page.locator("input[type='text'], input:not([type])").first.fill(ADMIN_USERNAME)

    # 填写错误密码
    page.locator("input[type='password']").first.fill("wrong_password_12345")

    # 点击登录按钮
    page.locator('button:has-text("登录"), button[type="submit"]').first.click()

    # 等待错误提示出现
    error_locator = page.locator(
        ".ant-message-error, .ant-message .ant-message-notice-content, "
        ".ant-alert-error, [class*='error'], .ant-form-item-explain-error"
    ).first

    try:
        expect(error_locator).to_be_visible(timeout=8000)
    except AssertionError:
        # 备选检查：页面未跳转也说明登录失败
        current_url = page.url
        assert "/login" in current_url, (
            f"使用错误密码登录后不应跳转, 当前 URL: {current_url}"
        )


# ---------------------------------------------------------------------------
# 3. Agent Management (API Tests)
# ---------------------------------------------------------------------------


def test_create_agent_requires_auth(page: Page):
    """POST /api/agents/create-token 未携带认证信息时应返回 401。"""
    response = page.request.post(
        f"{BASE_URL}/api/agents/create-token",
        data={"name": "test-no-auth-agent"},
        headers={"Content-Type": "application/json"},
    )
    assert response.status == 401, f"期望 401, 实际 {response.status}"


def test_create_agent_with_auth_returns_api_key(page: Page, auth_headers):
    """携带有效 token 创建 Agent，返回的 api_key 应以 'abk_' 开头。"""
    import time
    agent_name = f"test-agent-{int(time.time())}"
    response = page.request.post(
        f"{BASE_URL}/api/agents/create-token",
        data={"name": agent_name},
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert response.ok, f"创建 Agent 失败: {response.status} {response.text}"
    body = response.json()
    api_key = body.get("api_key")
    assert api_key, f"响应中未找到 api_key: {body}"
    assert api_key.startswith("abk_"), f"api_key 应以 'abk_' 开头, 实际: {api_key}"


def test_list_agents_requires_auth(page: Page):
    """GET /api/agents/ 未携带认证信息时应返回 401。"""
    response = page.request.get(f"{BASE_URL}/api/agents/")
    assert response.status == 401, f"期望 401, 实际 {response.status}"


def test_list_agents_with_auth_returns_list(page: Page, auth_headers):
    """携带有效 token 获取 Agent 列表，应返回数组。"""
    response = page.request.get(
        f"{BASE_URL}/api/agents/",
        headers=auth_headers,
    )
    assert response.ok, f"获取 Agent 列表失败: {response.status} {response.text}"
    body = response.json()
    assert isinstance(body, list), f"期望返回数组, 实际类型: {type(body).__name__}"


# ---------------------------------------------------------------------------
# 4. Navigation (UI Tests)
# ---------------------------------------------------------------------------


def _login_and_wait(page: Page):
    """辅助函数：登录并等待跳转到主页面。"""
    page.goto(f"{BASE_URL}/login")
    page.wait_for_load_state("networkidle")

    username_input = page.locator('input[placeholder*="用户名"], input[id*="user"], input[name*="user"]').first
    if username_input.is_visible():
        username_input.fill(ADMIN_USERNAME)
    else:
        page.locator("input[type='text'], input:not([type])").first.fill(ADMIN_USERNAME)

    page.locator("input[type='password']").first.fill(ADMIN_PASSWORD)
    page.locator('button:has-text("登录"), button[type="submit"]').first.click()

    page.wait_for_url(re.compile(rf"^{re.escape(BASE_URL)}/(?!login).*$"), timeout=15000)
    page.wait_for_load_state("networkidle")


def test_main_page_shows_navigation(page: Page):
    """主页面应显示导航菜单项：对话、群组、Agent、工作流。"""
    _login_and_wait(page)

    # 等待侧边栏菜单加载
    page.wait_for_selector(".ant-menu, nav, [class*='menu'], [class*='sidebar']", timeout=10000)

    # 检查四个核心菜单项
    expected_items = ["对话", "群组", "Agent", "工作流"]
    for item in expected_items:
        found = page.locator(f"text={item}").count() > 0
        assert found, f"未找到导航菜单项: '{item}'"


def test_agent_page_opens(page: Page):
    """点击 Agent 菜单项后应导航到 Agent 视图。"""
    _login_and_wait(page)

    page.wait_for_selector(".ant-menu, nav, [class*='menu'], [class*='sidebar']", timeout=10000)

    # 点击 Agent 菜单项
    agent_menu_item = page.locator(
        ".ant-menu-item:has-text('Agent'), "
        "a:has-text('Agent'), "
        "[class*='menu']:has-text('Agent'), "
        "span:has-text('Agent')"
    ).first

    agent_menu_item.click()

    page.wait_for_load_state("networkidle")

    current_url = page.url
    page_text = page.locator("body").inner_text()

    has_agent_view = (
        "/agent" in current_url.lower()
        or "Agent" in page_text
        or "agent" in page_text.lower()
    )
    assert has_agent_view, (
        f"点击 Agent 菜单后未进入 Agent 视图。URL: {current_url}"
    )
