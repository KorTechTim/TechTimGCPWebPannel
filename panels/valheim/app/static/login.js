'use strict';
const changingPassword = location.pathname === '/change-password';
const form = document.getElementById('login-form');
if (changingPassword) {
  document.getElementById('login-title').textContent = '새 패널 비밀번호 설정';
  document.getElementById('login-description').textContent = '8자 이상의 새 비밀번호로 서버를 보호하세요.';
  document.getElementById('username-label').hidden = true;
  document.getElementById('username').required = false;
  document.getElementById('confirm-label').hidden = false;
  document.getElementById('confirm-password').required = true;
  document.getElementById('password').minLength = 8;
  document.getElementById('password').autocomplete = 'new-password';
  document.getElementById('login-submit').textContent = '비밀번호 저장';
  document.getElementById('initial-hint').hidden = true;
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = document.getElementById('login-submit');
  const errorBox = document.getElementById('login-error');
  errorBox.textContent = '';
  const password = document.getElementById('password').value;
  if (changingPassword && password !== document.getElementById('confirm-password').value) {
    errorBox.textContent = '새 비밀번호와 확인 값이 다릅니다.';
    return;
  }
  button.disabled = true;
  try {
    const response = await fetch(changingPassword ? '/api/auth/change-password' : '/api/auth/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(changingPassword ? {new_password: password} : {username: document.getElementById('username').value, password}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '입력한 내용을 확인해주세요.');
    location.assign(data.redirect);
  } catch (error) { errorBox.textContent = error.message; }
  finally { button.disabled = false; }
});
