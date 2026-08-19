const header = document.querySelector('.site-header');
const navToggle = document.querySelector('.nav-toggle');
const navLinks = document.querySelector('.nav-links');
const appScreen = document.querySelector('#app-screen');
const screenButtons = document.querySelectorAll('[data-screen]');

window.addEventListener('scroll', () => {
  header.classList.toggle('scrolled', window.scrollY > 16);
}, { passive: true });

navToggle.addEventListener('click', () => {
  const open = navLinks.classList.toggle('open');
  navToggle.setAttribute('aria-expanded', String(open));
});

navLinks.addEventListener('click', event => {
  if (event.target.closest('a')) {
    navLinks.classList.remove('open');
    navToggle.setAttribute('aria-expanded', 'false');
  }
});

screenButtons.forEach(button => {
  button.addEventListener('click', () => {
    const mode = button.dataset.screen;
    screenButtons.forEach(item => item.classList.toggle('active', item === button));
    appScreen.style.opacity = '0';
    window.setTimeout(() => {
      appScreen.src = `assets/app-${mode}.png`;
      appScreen.alt = `DO编辑器${mode === 'light' ? '浅色' : '深色'}界面`;
      appScreen.style.opacity = '1';
    }, 150);
  });
});

const observer = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.12 });

document.querySelectorAll('.reveal').forEach(element => observer.observe(element));
document.querySelector('#year').textContent = String(new Date().getFullYear());
