/* Shared slide-deck runtime: navigation (buttons, keys, swipe, #n links),
   per-slide motion replay, count-up, SVG stroke drawing.
   Reduced motion / print / narrow screens → everything in its final state. */
(function () {
  var root = document.documentElement;
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var narrowQ = window.matchMedia ? matchMedia('(max-width: 760px)') : { matches: false };
  var slides = [], cur = 0, ui = {};

  function each(list, fn) { Array.prototype.forEach.call(list, fn); }
  function prepDraw(scope) {
    each(scope.querySelectorAll('path.draw, polyline.draw, line.draw'), function (p) {
      if (p.getTotalLength) p.style.setProperty('--len', p.getTotalLength());
    });
  }
  function countUp(scope) {
    each(scope.querySelectorAll('[data-count]'), function (n) {
      var end = parseFloat(n.dataset.count), dec = (n.dataset.count.split('.')[1] || '').length;
      if (reduce || isNaN(end)) { n.textContent = n.dataset.count; return; }
      var t0 = null;
      (function step(t) {
        if (!t0) t0 = t;
        var k = Math.min(1, (t - t0) / 900), e = 1 - Math.pow(1 - k, 3);
        n.textContent = k < 1 ? (end * e).toFixed(dec) : n.dataset.count;
        if (k < 1) requestAnimationFrame(step);
      })(performance.now());
    });
  }
  function animated(slide) { return slide.querySelectorAll('.rv, .stage'); }
  function reveal(slide) {
    each(animated(slide), function (el) { el.classList.add('in'); });
    slide.classList.add('in');
    countUp(slide);
  }
  function reset(slide) {
    if (reduce) return;
    each(animated(slide), function (el) { el.classList.remove('in'); });
    slide.classList.remove('in');
  }
  function fit() {
    if (narrowQ.matches) { root.style.removeProperty('--s'); return; }
    var s = Math.min(innerWidth / 1280, (innerHeight - 56) / 720);
    root.style.setProperty('--s', s.toFixed(4));
  }
  function show(n, fromHash) {
    n = Math.max(0, Math.min(slides.length - 1, n));
    if (n !== cur) {
      var prev = slides[cur];
      prev.classList.remove('active');
      prev.setAttribute('aria-hidden', 'true');
      setTimeout(function () { if (!prev.classList.contains('active')) reset(prev); }, 500);
    }
    cur = n;
    var s = slides[cur];
    s.classList.add('active');
    s.removeAttribute('aria-hidden');
    requestAnimationFrame(function () { requestAnimationFrame(function () { reveal(s); }); });
    ui.count.textContent = (cur + 1) + ' / ' + slides.length;
    ui.prev.disabled = cur === 0;
    ui.next.disabled = cur === slides.length - 1;
    ui.wrap.style.setProperty('--p', (cur + 1) / slides.length);
    if (!fromHash && history.replaceState) history.replaceState(null, '', '#' + (cur + 1));
  }
  function flash(el) {
    if (!el) return;
    el.classList.add('flash');
    setTimeout(function () { el.classList.remove('flash'); }, 1600);
  }
  function slideOf(id) {
    var el = id && document.getElementById(id);
    var s = el && el.closest('.slide');
    return s ? slides.indexOf(s) : -1;
  }
  function fromHash() {
    var h = decodeURIComponent(location.hash.slice(1));
    if (/^\d+$/.test(h)) return show(parseInt(h, 10) - 1, true);
    var i = slideOf(h);
    show(i >= 0 ? i : 0, true);
  }

  document.addEventListener('DOMContentLoaded', function () {
    slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
    slides.forEach(function (s, i) {
      s.setAttribute('role', 'group');
      s.setAttribute('aria-roledescription', '슬라이드');
      s.setAttribute('aria-label', (i + 1) + ' / ' + slides.length + (s.dataset.title ? ': ' + s.dataset.title : ''));
      each(s.querySelectorAll('.s-num'), function (el) { el.dataset.n = (i + 1) + ' / ' + slides.length; });
    });
    prepDraw(document);
    // outside links (sources, 원문) open in a new tab so the deck stays where it was
    each(document.querySelectorAll('a[href^="http"]'), function (a) {
      a.target = '_blank';
      a.rel = 'noopener';
    });
    ui.wrap = document.querySelector('.deck-ui');
    ui.prev = ui.wrap.querySelector('.prev');
    ui.next = ui.wrap.querySelector('.next');
    ui.count = ui.wrap.querySelector('.count');

    if (reduce) root.classList.add('static');      // still paged, just no animation
    if (narrowQ.matches) {                          // phones: plain vertical reading
      root.classList.add('stacked');
      slides.forEach(function (s) { s.classList.add('active'); reveal(s); });
      return;
    }
    fit();
    addEventListener('resize', fit);
    ui.prev.addEventListener('click', function () { show(cur - 1); });
    ui.next.addEventListener('click', function () { show(cur + 1); });
    document.addEventListener('keydown', function (e) {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      var k = e.key;
      if (k === 'ArrowRight' || k === 'PageDown' || (k === ' ' && !e.shiftKey)) { e.preventDefault(); show(cur + 1); }
      else if (k === 'ArrowLeft' || k === 'PageUp' || (k === ' ' && e.shiftKey)) { e.preventDefault(); show(cur - 1); }
      else if (k === 'Home') { e.preventDefault(); show(0); }
      else if (k === 'End') { e.preventDefault(); show(slides.length - 1); }
    });
    var x0 = null;
    document.addEventListener('touchstart', function (e) { x0 = e.touches[0].clientX; }, { passive: true });
    document.addEventListener('touchend', function (e) {
      if (x0 === null) return;
      var dx = e.changedTouches[0].clientX - x0; x0 = null;
      if (Math.abs(dx) > 50) show(cur + (dx < 0 ? 1 : -1));
    });
    // in-deck links: citation [n] → source slide; source number → back to where it was cited
    var from = null;   // {src: 'src-n', slide: index, id: citation anchor id}
    document.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('a[href^="#"]');
      if (!a) return;
      var target = a.getAttribute('href').slice(1);
      if (a.classList.contains('back')) {
        var li = a.closest('li');
        if (from && li && from.src === li.id) target = from.id;   // return to the click origin
      } else if (/^src-\d+$/.test(target) && a.id) {
        from = { src: target, slide: cur, id: a.id };
      }
      var i = slideOf(target);
      if (i >= 0) { e.preventDefault(); show(i); flash(document.getElementById(target)); }
    });
    addEventListener('hashchange', fromHash);
    addEventListener('beforeprint', function () { slides.forEach(reveal); });
    fromHash();
  });
})();
