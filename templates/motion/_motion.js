/* Shared motion runtime: reveal-on-scroll, SVG stroke drawing, count-up.
   Reduced motion or print → final state immediately. No hover-only content. */
(function () {
  var root = document.documentElement;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function finalize(el) {
    el.classList.add('in');
    el.querySelectorAll('[data-count]').forEach(function (n) { n.textContent = n.dataset.count; });
  }
  function prepDraw(scope) {
    scope.querySelectorAll('path.draw, polyline.draw, line.draw').forEach(function (p) {
      var len = p.getTotalLength ? p.getTotalLength() : 0;
      p.style.setProperty('--len', len);
    });
  }
  function countUp(el) {
    el.querySelectorAll('[data-count]').forEach(function (n) {
      var end = parseFloat(n.dataset.count), dec = (n.dataset.count.split('.')[1] || '').length;
      var t0 = null, dur = 900;
      function step(t) {
        if (!t0) t0 = t;
        var k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
        n.textContent = (end * e).toFixed(dec);
        if (k < 1) requestAnimationFrame(step); else n.textContent = n.dataset.count;
      }
      requestAnimationFrame(step);
    });
  }
  window.MotionKit = { reduce: reduce, prepDraw: prepDraw };
  document.addEventListener('DOMContentLoaded', function () {
    prepDraw(document);
    var items = document.querySelectorAll('.rv, .stage');
    if (reduce || !('IntersectionObserver' in window)) {
      root.classList.add('static');
      items.forEach(finalize);
      return;
    }
    root.classList.add('motion');
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        en.target.classList.add('in');
        countUp(en.target);
        io.unobserve(en.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.12 });
    items.forEach(function (el) { io.observe(el); });
    window.addEventListener('beforeprint', function () { items.forEach(finalize); });
  });
})();
