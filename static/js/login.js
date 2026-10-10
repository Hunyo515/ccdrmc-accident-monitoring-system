const password = document.getElementById('password');
const passwordToggle = document.getElementById('password-toggle');
passwordToggle.addEventListener('click', () => {
  const show = password.type === 'password';
  password.type = show ? 'text' : 'password';
  passwordToggle.textContent = show ? 'Hide' : 'Show';
  passwordToggle.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  passwordToggle.setAttribute('aria-pressed', String(show));
});
const video = document.getElementById('background-video');
const motion = document.getElementById('motion-toggle');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
function updateMotion() {
  motion.textContent = video.paused ? 'Play background' : 'Pause background';
}
async function startVideo() {
  if (reducedMotion.matches) { video.pause(); motion.hidden = true; return; }
  motion.hidden = false;
  try { await video.play(); } catch (_) { /* Keep the readable static background. */ }
  updateMotion();
}
motion.addEventListener('click', async () => {
  if (video.paused) { try { await video.play(); } catch (_) {} } else video.pause();
  updateMotion();
});
video.addEventListener('error', () => { motion.hidden = true; });
reducedMotion.addEventListener('change', startVideo);
startVideo();
