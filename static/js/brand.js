// Central, server-owned public brand projection. Compatibility identifiers
// (storage keys, headers, data paths) intentionally do not live here.

const FALLBACK = Object.freeze({
  product_name: 'OM Automate',
  assistant_name: 'OM',
  positioning: 'Your private AI operating system',
  assets: Object.freeze({
    favicon: '/static/brand/om-mark.svg',
    apple_touch_icon: '/static/brand/om-icon-192.png',
    icon: '/static/brand/om-mark.svg',
    alt_text: 'OM Automate',
  }),
  titles: Object.freeze({ default: 'OM Automate', login: 'Sign in · OM Automate', legal: 'Legal & source · OM Automate', routes: Object.freeze({ '/': 'Chat · OM Automate' }) }),
  navigation: Object.freeze({ approvals: 'Approval Centre' }),
  links: Object.freeze({ legal: '/static/legal.html', source: 'https://github.com/odysseus-dev/odysseus' }),
  copy: Object.freeze({
    welcome: 'Ready when you are. Ask OM, or type /setup to connect a model.',
    empty_state: 'Nothing needs your attention right now.',
    message_placeholder: 'Message OM…',
    default_persona: "You are OM, the user's private executive AI companion inside OM Automate. Be clear, grounded and discreet. Plan before acting, use only permitted tools, request approval for consequential actions, verify outcomes and state uncertainty honestly.",
  }),
  theme: Object.freeze({ accent: '#69d2e7', signal: '#f0a45d' }),
});

let _brand = null;

function _valid(value) {
  return value && typeof value === 'object'
    && typeof value.product_name === 'string'
    && typeof value.assistant_name === 'string'
    && value.assets && value.titles && value.copy && value.links;
}

function _readInjected() {
  if (typeof document === 'undefined') return null;
  const node = document.getElementById('om-brand-config');
  if (!node) return null;
  try {
    const parsed = JSON.parse(node.textContent || '');
    return _valid(parsed) ? parsed : null;
  } catch (_) {
    return null;
  }
}

export function getBrand() {
  if (!_brand) _brand = _readInjected() || FALLBACK;
  return _brand;
}

export async function loadBrand() {
  const injected = _readInjected();
  if (injected) {
    _brand = injected;
    return _brand;
  }
  try {
    const response = await fetch('/static/manifest.json', { credentials: 'same-origin', cache: 'no-cache' });
    if (response.ok) {
      const manifest = await response.json();
      if (_valid(manifest.om_automate)) _brand = manifest.om_automate;
    }
  } catch (_) {}
  return getBrand();
}

function _lookup(config, path) {
  return String(path || '').split('.').reduce((value, key) => value && value[key], config);
}

function _setBrandAttributes(config) {
  document.querySelectorAll('[data-brand-text]').forEach(node => {
    const value = _lookup(config, node.dataset.brandText);
    if (typeof value === 'string') node.textContent = value;
  });
  for (const [dataName, attribute] of [
    ['brandPlaceholder', 'placeholder'], ['brandAriaLabel', 'aria-label'],
    ['brandTitle', 'title'], ['brandHref', 'href'], ['brandSrc', 'src'],
  ]) {
    document.querySelectorAll(`[data-${dataName.replace(/[A-Z]/g, c => '-' + c.toLowerCase())}]`).forEach(node => {
      const value = _lookup(config, node.dataset[dataName]);
      if (typeof value === 'string') node.setAttribute(attribute, value);
    });
  }
}

export async function applyBrand() {
  const config = await loadBrand();
  const page = document.body?.dataset.brandPage || '';
  const routeTitle = config.titles?.routes?.[window.location.pathname];
  document.title = page === 'login'
    ? config.titles.login
    : page === 'legal'
      ? config.titles.legal
      : (routeTitle || config.titles.default || config.product_name);
  document.documentElement.style.setProperty('--om-brand-accent', config.theme?.accent || FALLBACK.theme.accent);
  document.documentElement.style.setProperty('--om-brand-signal', config.theme?.signal || FALLBACK.theme.signal);
  _setBrandAttributes(config);

  const favicon = document.querySelector("link[rel='icon']");
  if (favicon && config.assets?.favicon && !favicon.dataset.routeIcon) favicon.href = config.assets.favicon;
  const touch = document.querySelector("link[rel='apple-touch-icon']");
  if (touch && config.assets?.apple_touch_icon && !touch.dataset.routeIcon) touch.href = config.assets.apple_touch_icon;
  document.dispatchEvent(new CustomEvent('om-automate:brand-ready', { detail: config }));
  return config;
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { void applyBrand(); }, { once: true });
  } else {
    void applyBrand();
  }
}

export default { getBrand, loadBrand, applyBrand };
