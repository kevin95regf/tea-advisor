/**
 * 请求封装：统一超时、错误码翻译、本地缓存。
 *
 * 小程序的 wx.request 超时上限比浏览器宽松，这里显式设为 60s，
 * 因为双 Agent 串行要 12-18 秒。真实上线建议改异步任务 + 轮询。
 */
const ENV = require('../config/env.js');

const CACHE_PREFIX = 'ta_cache_';

/** 把各种失败翻译成人能看懂的话 */
function friendlyError(err, statusCode) {
  const detail = (err && err.detail) || {};
  const code = detail.code || '';
  const msg = detail.message || (err && err.errMsg) || '';

  if (code === 'AGENT1_FAILED') {
    return '没能看懂你吃了什么。可以再说具体一点，比如「中午吃了碗牛肉面加一杯冰可乐」。';
  }
  if (code === 'INTERNAL_ERROR') {
    return '服务出了点问题，稍后再试试。';
  }
  if (statusCode === 422) {
    return msg || '这条描述没能解析成功，换个说法再试一次。';
  }
  if (statusCode === 429) {
    return '请求有点频繁，休息一下再试。';
  }
  if (statusCode >= 500) {
    return '服务暂时不可用，请稍后重试。';
  }
  if (msg.indexOf('timeout') >= 0) {
    return '等待时间太长了。可能是网络慢，也可能是模型正忙，再试一次通常就好了。';
  }
  if (msg.indexOf('fail') >= 0) {
    return (
      '连不上后端服务。请检查三件事：\n' +
      '1) 后端是否在运行（uvicorn app.main:app --host 0.0.0.0 --port 8000）\n' +
      '2) miniprogram/config/env.js 里的 IP 是否是电脑当前的局域网 IP\n' +
      '3) 开发者工具「详情 → 本地设置」是否勾选了「不校验合法域名」'
    );
  }
  return msg || '请求失败，请重试。';
}

/** 基础请求。返回 Promise，失败时 reject 一个带 message 的对象 */
function request(path, { method = 'GET', data = null, timeout } = {}) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: ENV.API_BASE_URL + path,
      method,
      data,
      timeout: timeout || ENV.TIMEOUT_MS,
      header: { 'content-type': 'application/json' },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
          return;
        }
        reject({
          message: friendlyError(res.data, res.statusCode),
          statusCode: res.statusCode,
          raw: res.data,
        });
      },
      fail(err) {
        reject({ message: friendlyError(err), statusCode: 0, raw: err });
      },
    });
  });
}

/** 自检接口，用于首页提示后端是否就绪 */
function healthz() {
  return request('/healthz', { timeout: 8000 });
}

/** 饮片目录 */
function catalog() {
  return request('/api/catalog/herbs');
}

/** 免责声明（前端不硬编码文案，统一从后端取） */
function disclaimer() {
  return request('/api/disclaimer');
}

/**
 * 核心：解析 + 推荐。
 * 带本地缓存：相同体质 + 相同口述在 TTL 内直接返回上次结果。
 */
function analyze({ text, constitution }) {
  const cacheKey =
    CACHE_PREFIX +
    constitution +
    '_' +
    text.trim().replace(/\s+/g, '').slice(0, 80);

  try {
    const cached = wx.getStorageSync(cacheKey);
    if (cached && cached.__ts && Date.now() - cached.__ts < ENV.CACHE_TTL_MS) {
      console.log('[tea-advisor] 命中本地缓存，跳过请求');
      return Promise.resolve(Object.assign({}, cached.data, { __fromCache: true }));
    }
  } catch (e) {
    // 缓存读失败不影响主流程
  }

  return request('/api/analyze', {
    method: 'POST',
    data: { text, constitution_override: constitution },
  }).then((res) => {
    try {
      wx.setStorageSync(cacheKey, { __ts: Date.now(), data: res });
    } catch (e) {
      // 存不下就算了
    }
    return res;
  });
}

function clearCache() {
  try {
    const info = wx.getStorageInfoSync();
    (info.keys || [])
      .filter((k) => k.indexOf(CACHE_PREFIX) === 0)
      .forEach((k) => wx.removeStorageSync(k));
  } catch (e) {
    // ignore
  }
}

module.exports = { request, healthz, catalog, disclaimer, analyze, clearCache, friendlyError };
