// Inject BreadcrumbList JSON-LD structured data on every page.
//
// Google uses BreadcrumbList schema.org markup to display breadcrumbs
// in search results instead of the automatic "GitHub Pages documentation"
// path label that it applies to github.io sites.
//
// The breadcrumb is built from the page URL: the site root is "Senpy",
// and each path segment becomes a breadcrumb item (e.g. /renpy-linter/
// → "Senpy > Ren'Py Linter"). Page titles are taken from the <title>
// element (MkDocs Material sets it to the page heading + site name).
//
// This script runs after DOMContentLoaded — MkDocs Material uses
// navigation.instant (SPA mode), so we also listen for
// 'contentUpdated' events to re-inject on page transitions.

(function () {
    'use strict';

    function injectBreadcrumbJsonLd() {
        // Remove any previously-injected JSON-LD (SPA navigation).
        var existing = document.getElementById('senpy-breadcrumb-jsonld');
        if (existing) {
            existing.remove();
        }

        // Build breadcrumb items from the URL path.
        var path = window.location.pathname;
        // Remove trailing slash and the leading /senpy/ prefix.
        var cleanPath = path.replace(/\/+$/, '').replace(/^\/senpy\//, '');
        var segments = cleanPath ? cleanPath.split('/') : [];

        var baseUrl = 'https://xilleet.github.io/senpy/';
        var items = [{
            '@type': 'ListItem',
            position: 1,
            name: 'Senpy',
            item: baseUrl
        }];

        // Build a human-readable name from each path segment.
        // /renpy-linter/ → "Ren'Py Linter"
        // /rules/rpy1xx-state/ → "RPY1xx — Variables & State"
        // /cli-reference/ → "CLI Reference"
        function segmentToTitle(seg) {
            // Try to find the segment in the nav sidebar (most accurate).
            var navLinks = document.querySelectorAll('.md-nav__link');
            for (var i = 0; i < navLinks.length; i++) {
                var link = navLinks[i];
                var href = link.getAttribute('href') || '';
                // MkDocs Material may use relative or absolute hrefs.
                if (href.indexOf(seg) !== -1 || href.indexOf(seg.replace(/-/g, ' ')) !== -1) {
                    var text = link.textContent.trim();
                    if (text) return text;
                }
            }
            // Fallback: capitalize and replace hyphens with spaces.
            return seg.replace(/-/g, ' ').replace(/\b\w/g, function (c) {
                return c.toUpperCase();
            });
        }

        var currentUrl = baseUrl;
        for (var i = 0; i < segments.length; i++) {
            currentUrl += segments[i] + '/';
            items.push({
                '@type': 'ListItem',
                position: i + 2,
                name: segmentToTitle(segments[i]),
                item: currentUrl
            });
        }

        var jsonLd = {
            '@context': 'https://schema.org',
            '@type': 'BreadcrumbList',
            itemListElement: items
        };

        var script = document.createElement('script');
        script.type = 'application/ld+json';
        script.id = 'senpy-breadcrumb-jsonld';
        script.textContent = JSON.stringify(jsonLd, null, 2);
        document.head.appendChild(script);
    }

    // Run on initial page load.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injectBreadcrumbJsonLd);
    } else {
        injectBreadcrumbJsonLd();
    }

    // Re-inject on SPA navigation (MkDocs Material navigation.instant).
    document.addEventListener('DOMContentSwap', injectBreadcrumbJsonLd);
    // Material 9.x uses a different event name for content updates.
    var observer = new MutationObserver(function (mutations) {
        for (var i = 0; i < mutations.length; i++) {
            if (mutations[i].addedNodes.length > 0) {
                // Check if the main content was swapped (SPA navigation).
                for (var j = 0; j < mutations[i].addedNodes.length; j++) {
                    var node = mutations[i].addedNodes[j];
                    if (node.nodeType === 1 && (
                        node.classList.contains('md-main') ||
                        node.querySelector && node.querySelector('.md-content')
                    )) {
                        // Defer to next tick to let MkDocs update the title.
                        setTimeout(injectBreadcrumbJsonLd, 50);
                        break;
                    }
                }
            }
        }
    });
    observer.observe(document.body, { childList: true, subtree: true });
})();
