// The site's languages: English at the root, the others under docs/<slug>/.
//
// The picker at the top of every page links to the same page in another
// language, and a click remembers the choice. Only the root page (the one
// with data-lang-auto on <html>, which loads this file without defer so it
// decides before anything is drawn) switches by itself: to the remembered
// choice or, without one, to the first language the browser prefers that
// the site has -- which is what the app does with the desktop's locale.
// A translated page never redirects: a link someone shared opens as shared.
//
// Storage can be missing or refused (private windows, blocked site data).
// Without it the site works the same and only forgets the choice.
(function () {
  'use strict';

  var KEY = 'openemux.lang';
  var SLUGS = ['en', 'pt-br', 'es', 'fr', 'de', 'ja', 'zh-cn', 'ta'];

  // A browser tag ("pt-BR", "pt", "zh-Hans-CN", "fr-CA") to one of ours.
  function slugFor(tag) {
    var parts = String(tag || '').toLowerCase().split('-');
    if (parts[0] === 'pt') return 'pt-br';
    if (parts[0] === 'zh') return 'zh-cn';
    return SLUGS.indexOf(parts[0]) >= 0 ? parts[0] : null;
  }

  function remembered() {
    try {
      var value = window.localStorage.getItem(KEY);
      return SLUGS.indexOf(value) >= 0 ? value : null;
    } catch (e) {
      return null;
    }
  }

  function remember(slug) {
    try {
      window.localStorage.setItem(KEY, slug);
    } catch (e) {
      // No storage: the choice lasts for this click only.
    }
  }

  function fromBrowser() {
    var preferred = navigator.languages && navigator.languages.length
      ? navigator.languages
      : [navigator.language];
    for (var i = 0; i < preferred.length; i++) {
      var slug = slugFor(preferred[i]);
      if (slug) return slug;
    }
    return 'en';
  }

  if (document.documentElement.hasAttribute('data-lang-auto')) {
    var slug = remembered() || fromBrowser();
    if (slug !== 'en') {
      // replace: the Back button does not land here again.
      window.location.replace(slug + '/' + window.location.hash);
      return;
    }
  }

  function wire() {
    var links = document.querySelectorAll('.lang-switch a[hreflang]');
    for (var i = 0; i < links.length; i++) {
      links[i].addEventListener('click', function () {
        remember(slugFor(this.getAttribute('hreflang')) || 'en');
      });
    }
    // Close the open menu on a click elsewhere or on Escape.
    var picker = document.querySelector('.lang-switch');
    if (!picker) return;
    document.addEventListener('click', function (e) {
      if (picker.open && !picker.contains(e.target)) picker.open = false;
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && picker.open) {
        picker.open = false;
        picker.querySelector('summary').focus();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
