const api = require('../../utils/request.js');
const fmt = require('../../utils/format.js');

/** 规则 id → 可读文案（与后端 services/matcher.py 的 RULES 对应） */
const RULE_LABELS = {
  greasy: '油腻餐后偏消食',
  cold_intake: '生冷之后偏温中',
  spicy: '辛辣燥热偏生津',
  sweet_heavy: '甜腻餐后偏化湿',
  late_night: '夜宵偏和胃',
  constitution_default: '按体质默认方向',
};

function sec(ms) {
  if (ms === null || ms === undefined) return '-';
  return (ms / 1000).toFixed(1);
}

Page({
  data: {
    text: '',
    constitution: 'balanced',
    loading: true,
    error: '',
    parsed: { foods: [], uncertain: [], uncertainText: '' },
    recs: [],
    basis: { constitutionLabel: '', ruleHits: [], ruleText: '', guardrail: [] },
    meta: {},
    userMessage: '',
    fromCache: false,
    disclaimerText:
      '本内容基于中医饮食养生常识与药食同源食材，仅供日常饮食参考，不构成医疗建议。',
  },

  onLoad(query) {
    const text = decodeURIComponent(query.text || '');
    const constitution = query.constitution || 'balanced';
    this.setData({ text, constitution });
    this.loadDisclaimer();
    this.run();
  },

  loadDisclaimer() {
    api
      .disclaimer()
      .then((d) => {
        if (d && d.text) this.setData({ disclaimerText: d.text });
      })
      .catch(() => {
        // 取不到就用内置文案，保证页面上一定有免责声明
      });
  },

  run() {
    this.setData({ loading: true, error: '' });
    api
      .analyze({ text: this.data.text, constitution: this.data.constitution })
      .then((res) => this.render(res))
      .catch((err) => {
        this.setData({
          loading: false,
          error: (err && err.message) || '请求失败，请重试。',
        });
      });
  },

  render(res) {
    const parsed = fmt.decorateParsed(res.parsed);
    parsed.uncertainText = (res.parsed.uncertain_items || []).join('、');

    const basisRaw = res.basis || {};
    const ruleHits = basisRaw.rule_hits || [];
    const metaRaw = res.meta || {};

    this.setData({
      loading: false,
      error: '',
      parsed,
      recs: fmt.decorateRecommendations(res.recommendations),
      basis: {
        constitutionLabel: basisRaw.constitution_label || '',
        ruleHits,
        ruleText: ruleHits.map((id) => RULE_LABELS[id] || id).join('、'),
        guardrail: basisRaw.guardrail_applied || [],
      },
      meta: {
        totalSec: sec(metaRaw.total_ms),
        agent1Sec: sec(metaRaw.agent1_ms),
        agent2Sec: sec(metaRaw.agent2_ms),
        model: metaRaw.model || '',
        degraded: !!metaRaw.degraded,
      },
      userMessage: res.user_message || '',
      fromCache: !!res.__fromCache,
    });
  },

  retry() {
    this.run();
  },

  back() {
    wx.navigateBack({
      fail: () => {
        wx.redirectTo({ url: '/pages/index/index' });
      },
    });
  },
});
