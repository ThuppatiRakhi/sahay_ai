/**
 * SahayAI - Shared Navigation & Profile Dropdown Controller
 * Handles Profile Icon dropdown menu, outside click detection, Escape key handling,
 * and unified session logout.
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.SahayNav = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function initProfileDropdown(options) {
    options = options || {};
    var btn = document.getElementById(options.buttonId || 'profileIconBtn');
    var menu = document.getElementById(options.menuId || 'profileDropdownMenu');
    var container = document.getElementById(options.containerId || 'profileMenuContainer');
    var nameEl = document.getElementById(options.nameId || 'dropdownCitizenName');
    var idEl = document.getElementById(options.idElementId || 'dropdownCitizenId');
    var avatarImg = document.getElementById(options.avatarImgId || 'profileAvatarImg');
    var avatarFallback = document.getElementById(options.avatarFallbackId || 'profileAvatarFallback');
    var logoutItem = document.getElementById(options.logoutItemId || 'dropdownLogoutItem');

    if (!btn || !menu) return null;

    function openMenu() {
      menu.classList.add('show');
      btn.setAttribute('aria-expanded', 'true');
    }

    function closeMenu() {
      menu.classList.remove('show');
      btn.setAttribute('aria-expanded', 'false');
    }

    function toggleMenu(e) {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (menu.classList.contains('show')) {
        closeMenu();
      } else {
        openMenu();
      }
    }

    btn.addEventListener('click', toggleMenu);

    // Close on outside click
    document.addEventListener('click', function (e) {
      if (container && !container.contains(e.target)) {
        closeMenu();
      }
    });

    // Close on Escape key
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' || e.keyCode === 27) {
        if (menu.classList.contains('show')) {
          closeMenu();
          btn.focus();
        }
      }
    });

    // Close on clicking any item link (except logout which handles its own navigation)
    var links = menu.querySelectorAll('.profile-dropdown-item:not(.logout-item)');
    links.forEach(function (link) {
      link.addEventListener('click', function () {
        closeMenu();
      });
    });

    // Wire logout item
    if (logoutItem) {
      logoutItem.addEventListener('click', async function (e) {
        e.preventDefault();
        closeMenu();
        if (typeof window.logoutCitizen === 'function') {
          await window.logoutCitizen();
        } else if (typeof logoutCitizen === 'function') {
          await logoutCitizen();
        } else {
          try {
            await fetch('/auth/logout', { method: 'POST', credentials: 'include' });
          } catch (err) {
            console.error('Logout error:', err);
          }
          window.location.href = 'login.html';
        }
      });
    }

    // Set user info
    function setUserInfo(user) {
      if (!user) return;
      if (nameEl) {
        nameEl.textContent = user.name || user.full_name || user.email || 'Citizen';
      }
      if (idEl) {
        if (user.citizen_id || user.id) {
          idEl.textContent = user.citizen_id || ('ID: ' + String(user.id).slice(0, 8));
          idEl.style.display = 'block';
        } else {
          idEl.style.display = 'none';
        }
      }
      if (user.avatar_url || user.profile_picture) {
        if (avatarImg) {
          avatarImg.src = user.avatar_url || user.profile_picture;
          avatarImg.style.display = 'block';
        }
        if (avatarFallback) {
          avatarFallback.style.display = 'none';
        }
      }
    }

    return {
      open: openMenu,
      close: closeMenu,
      toggle: toggleMenu,
      setUserInfo: setUserInfo
    };
  }

  return {
    initProfileDropdown: initProfileDropdown
  };
});

