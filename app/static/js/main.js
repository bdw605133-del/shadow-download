(function () {
  'use strict';

  const toggle = document.querySelector('[data-nav-toggle]');
  const nav = document.getElementById('primary-nav');

  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      const open = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!open));
      nav.classList.toggle('is-open', !open);
    });
    nav.addEventListener('click', function (event) {
      if (event.target.closest('a')) {
        toggle.setAttribute('aria-expanded', 'false');
        nav.classList.remove('is-open');
      }
    });
  }

  const reveals = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && reveals.length) {
    const observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    reveals.forEach(function (element) { observer.observe(element); });
  } else {
    reveals.forEach(function (element) { element.classList.add('is-visible'); });
  }

  document.querySelectorAll('[data-copy]').forEach(function (button) {
    button.addEventListener('click', async function () {
      const target = document.getElementById(button.getAttribute('data-copy'));
      if (!target) return;
      const text = target.textContent.trim();
      try {
        await navigator.clipboard.writeText(text);
        const original = button.textContent;
        button.textContent = 'Copied';
        window.setTimeout(function () { button.textContent = original; }, 1800);
      } catch (error) {
        button.textContent = 'Select manually';
      }
    });
  });

  document.querySelectorAll('[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      const message = form.getAttribute('data-confirm');
      if (message && !window.confirm(message)) event.preventDefault();
    });
  });
})();
