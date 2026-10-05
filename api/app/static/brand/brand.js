// Loading screen: shown until the globe has its layer chips (or 8 seconds), and for at least 1.4 seconds.
(function () {
  var splash = document.getElementById('splash');
  if (!splash) return;
  var started = performance.now();
  var MIN = 1400;
  var MAX = 8000;
  function hide() {
    splash.classList.add('done');
    setTimeout(function () { splash.remove(); }, 900);
  }
  (function check() {
    var t = performance.now() - started;
    var ready = !!document.querySelector('#layers .chip');
    if ((ready && t >= MIN) || t >= MAX) hide();
    else setTimeout(check, 120);
  })();
})();
