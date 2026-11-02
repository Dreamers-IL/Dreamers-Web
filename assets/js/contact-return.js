/* "Back to where you were": the contact page has a return icon that takes the
   visitor to the exact spot (page and scroll position) from which they
   pressed a link to the contact page. Every page loads this one file. */
(function () {
  var KEY = "dhContactReturn";
  var RKEY = "dhContactRestore";

  /* session storage, with a fallback for frames that refuse it (the offline
     preview file keeps the pages in a frame inside one holder page) */
  function get(k) {
    try {
      var v = sessionStorage.getItem(k);
      if (v) return JSON.parse(v);
    } catch (e) {}
    try {
      return window.top["__" + k] || null;
    } catch (e) {}
    return null;
  }
  function set(k, v) {
    try {
      sessionStorage.setItem(k, JSON.stringify(v));
      return;
    } catch (e) {}
    try {
      window.top["__" + k] = v;
    } catch (e) {}
  }
  function del(k) {
    try {
      sessionStorage.removeItem(k);
    } catch (e) {}
    try {
      delete window.top["__" + k];
    } catch (e) {}
  }

  function pageName() {
    var m = location.pathname.match(/([^\/]+)\.html$/);
    if (m) return m[1];
    try {
      var h = (window.top.location.hash || "").replace(/^#/, "").split(/[?#]/)[0];
      if (h) return h;
    } catch (e) {}
    return "index";
  }

  /* remember where the visitor was the moment they pressed a link to the
     contact page */
  document.addEventListener(
    "click",
    function (e) {
      var a = e.target && e.target.closest ? e.target.closest("a") : null;
      if (!a) return;
      var href = a.getAttribute("href") || "";
      if (!/^contact\.html(\?|#|$)/.test(href)) return;
      var here = pageName();
      if (here === "contact") return;
      set(KEY, { p: here, y: Math.round(window.pageYOffset || 0) });
    },
    true,
  );

  /* arriving back: put the page at the scroll position it was left at */
  var r = get(RKEY);
  if (r && r.p === pageName()) {
    del(RKEY);
    var go = function () {
      window.scrollTo({ top: r.y || 0, left: 0, behavior: "instant" });
    };
    go();
    window.addEventListener("load", function () {
      go();
      setTimeout(go, 250);
      setTimeout(go, 800);
    });
  }

  /* the contact page's return icon */
  var btn = document.getElementById("returnBtn");
  if (btn) {
    btn.addEventListener("click", function () {
      var s = get(KEY);
      var target = s && s.p && s.p !== "contact" ? s.p : "index";
      set(RKEY, { p: target, y: s && s.p === target ? s.y : 0 });
      var a = document.createElement("a");
      a.setAttribute("href", target + ".html");
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
    });
  }
})();
