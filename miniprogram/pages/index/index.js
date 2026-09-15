const api = require('../../utils/request.js');
const fmt = require('../../utils/format.js');

const CONST_KEY = 'ta_constitution';

Page({
  data: {
    text: '',
    examples: [
      '中午吃了碗麻辣烫，还喝了杯冰可乐',
      '晚上火锅吃撑了，都是肉，还喝了啤酒',
      '早上就一杯冰美式，中午吃了份沙拉',
      '夜宵吃了炸鸡配奶茶',
    ],
    constitutions: fmt.CONSTITUTIONS,
    constIndex: 0,
    loading: false,
    backendOk: false,
    healthChecked: false,
  },

  onLoad() {
    // 恢复上次选择的体质
    let idx = 0;
    try {
      const saved = wx.getStorageSync(CONST_KEY);
      if (saved) {
        const found = fmt.CONSTITUTIONS.map((c) => c.id).indexOf(saved);
        if (found >= 0) idx = found;
      }
    } catch (e) {
      // ignore
    }
    this.setData({ constIndex: idx });
    this.checkBackend();
  },

  checkBackend() {
    api
      .healthz()
      .then((res) => {
        this.setData({ backendOk: true, healthChecked: true });
        if (res && res.credentials_ok === false) {
          wx.showToast({ title: '后端缺 API Key', icon: 'none', duration: 3000 });
        }
      })
      .catch(() => {
        this.setData({ backendOk: false, healthChecked: true });
      });
  },

  recheck() {
    wx.showLoading({ title: '检测中' });
    api
      .healthz()
      .then(() => {
        wx.hideLoading();
        this.setData({ backendOk: true, healthChecked: true });
        wx.showToast({ title: '连接正常', icon: 'success' });
      })
      .catch(() => {
        wx.hideLoading();
        this.setData({ backendOk: false, healthChecked: true });
        wx.showToast({ title: '仍然连不上', icon: 'none' });
      });
  },

  onInput(e) {
    this.setData({ text: e.detail.value });
  },

  useExample(e) {
    this.setData({ text: e.currentTarget.dataset.text });
  },

  onConstChange(e) {
    const idx = Number(e.detail.value);
    this.setData({ constIndex: idx });
    try {
      wx.setStorageSync(CONST_KEY, fmt.CONSTITUTIONS[idx].id);
    } catch (err) {
      // ignore
    }
  },

  submit() {
    const text = (this.data.text || '').trim();
    if (!text) {
      wx.showToast({ title: '先说说吃了什么', icon: 'none' });
      return;
    }
    // 提交前把后端状态相关的空态收起来
    this.setData({ loading: true });
    const constitution = fmt.CONSTITUTIONS[this.data.constIndex].id;
    wx.navigateTo({
      url:
        '/pages/result/result?text=' +
        encodeURIComponent(text) +
        '&constitution=' +
        constitution,
      complete: () => {
        this.setData({ loading: false });
      },
    });
  },
});
