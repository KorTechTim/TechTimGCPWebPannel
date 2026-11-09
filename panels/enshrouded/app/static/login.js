const loginForm = document.querySelector('#login-form');
const passwordForm = document.querySelector('#password-form');
const message = document.querySelector('#login-message');
async function request(url, body) { const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.detail || 'Request failed'); return data; }
loginForm.addEventListener('submit', async (event) => { event.preventDefault(); message.textContent = ''; const data = Object.fromEntries(new FormData(loginForm)); try { const result = await request('/api/auth/login', data); if (result.must_change_password) { loginForm.hidden = true; passwordForm.hidden = false; passwordForm.querySelector('input').focus(); } else location.href = '/'; } catch (error) { message.textContent = error.message; } });
passwordForm.addEventListener('submit', async (event) => { event.preventDefault(); message.textContent = ''; try { await request('/api/auth/change-password', Object.fromEntries(new FormData(passwordForm))); location.href = '/'; } catch (error) { message.textContent = error.message; } });
if (location.pathname === '/change-password') { loginForm.hidden = true; passwordForm.hidden = false; }
