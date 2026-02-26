// auth.js — login/register page logic

function showError(msg) {
  const el = document.getElementById('error-msg');
  el.textContent = msg;
  el.classList.add('show');
}
function hideError() {
  document.getElementById('error-msg').classList.remove('show');
}

function setLoading(btn, loading) {
  btn.disabled = loading;
  btn.textContent = loading ? '请稍候...' : btn.dataset.label;
}

document.addEventListener('DOMContentLoaded', () => {
  // Already logged in → redirect
  if (localStorage.getItem('token')) {
    window.location.href = '/';
    return;
  }

  const loginForm = document.getElementById('login-form');
  const registerForm = document.getElementById('register-form');
  const loginBtn = document.getElementById('login-btn');
  const registerBtn = document.getElementById('register-btn');
  loginBtn.dataset.label = '登录';
  registerBtn.dataset.label = '注册';

  document.getElementById('to-register').addEventListener('click', () => {
    loginForm.style.display = 'none';
    registerForm.style.display = 'block';
    hideError();
  });
  document.getElementById('to-login').addEventListener('click', () => {
    registerForm.style.display = 'none';
    loginForm.style.display = 'block';
    hideError();
  });

  // Login
  async function doLogin() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    if (!username || !password) { showError('请填写用户名和密码'); return; }
    hideError();
    setLoading(loginBtn, true);
    try {
      const res = await authAPI.login({ username, password });
      localStorage.setItem('token', res.token);
      localStorage.setItem('user', JSON.stringify(res.user));
      window.location.href = '/';
    } catch (e) {
      showError(e.message);
    } finally {
      setLoading(loginBtn, false);
    }
  }

  loginBtn.addEventListener('click', doLogin);
  document.getElementById('login-password').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doLogin();
  });

  // Register
  async function doRegister() {
    const username = document.getElementById('reg-username').value.trim();
    const nickname = document.getElementById('reg-nickname').value.trim();
    const password = document.getElementById('reg-password').value;
    if (!username || !password) { showError('请填写用户名和密码'); return; }
    if (password.length < 6) { showError('密码至少 6 位'); return; }
    hideError();
    setLoading(registerBtn, true);
    try {
      const res = await authAPI.register({ username, password, nickname: nickname || undefined });
      localStorage.setItem('token', res.token);
      localStorage.setItem('user', JSON.stringify(res.user));
      window.location.href = '/';
    } catch (e) {
      showError(e.message);
    } finally {
      setLoading(registerBtn, false);
    }
  }

  registerBtn.addEventListener('click', doRegister);
  document.getElementById('reg-password').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doRegister();
  });
});
