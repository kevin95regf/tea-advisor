const api = require('../../utils/request.js');
const fmt = require('../../utils/format.js');
const ENV = require('../../config/env.js');

const CONST_KEY = 'ta_constitution';
const MAX_LEN = 500;

Page({
  data: {
    text: '',
    examples: [
      '中午吃了碗麻辣烫，还喝了杯冰可乐',
      '晚上火锅吃撑了，都是肉，还喝了啤酒',
      '早上就一杯冰美式，中午吃了份沙拉',
      '夜宵吃了炸鸡配奶茶',
    ],
    maxLen: MAX_LEN,

    // 体质选择
    constitutions: fmt.CONSTITUTIONS,
    constIndex: 0,
    // 是否已明确选择过体质。false 时卡片显示"请选择"而不是假装是平和质
    constPicked: false,

    // 后端状态
    backendOk: false,
    healthChecked: false,
    healthMs: 0,
    apiBase: ENV.API_BASE_URL,

    loading: false,
    // 输入框聚焦标记：点示例后置 true，真机上能自动唤起键盘
    inputFocus: false,
    // 已用过的示例下标（只用于判断"这句加过了"，不参与渲染）
    usedExamples: [],
  },

  onLoad() {
    this.restoreConstitution();
    this.checkBackend();
  },

  // ------------------------------------------------------------
  // 体质
  // ------------------------------------------------------------
  /** 安全取当前体质。任何异常都回退到第一项，避免越界渲染失败 */
  currentConstitution() {
    const list = fmt.CONSTITUTIONS || [];
    if (!list.length) {
      return { id: 'balanced', label: '平和质', one_line: '' };
    }
    const i = Number(this.data.constIndex);
    if (!Number.isInteger(i) || i < 0 || i >= list.length) {
      return list[0];
    }
    return list[i];
  },

  restoreConstitution() {
    const list = fmt.CONSTITUTIONS || [];
    let idx = 0;
    let picked = false;
    try {
      const saved = wx.getStorageSync(CONST_KEY);
      if (saved) {
        const found = list.map((c) => c.id).indexOf(saved);
        if (found >= 0) {
          idx = found;
          picked = true;
        }
      }
    } catch (e) {
      // Storage 读失败就用默认值，不影响页面
    }
    this.setData({ constIndex: idx, constPicked: picked });
  },

  onConstChange(e) {
    const list = fmt.CONSTITUTIONS || [];
    let idx = Number(e.detail.value);
    // picker 理论上只会给合法下标，但跨版本/异常情况下仍可能越界
    if (!Number.isInteger(idx) || idx < 0 || idx >= list.length) {
      idx = 0;
    }
    this.setData({ constIndex: idx, constPicked: true });
    try {
      wx.setStorageSync(CONST_KEY, list[idx].id);
    } catch (err) {
      // ignore
    }
  },

  // ------------------------------------------------------------
  // 后端连通性
  // ------------------------------------------------------------
  checkBackend() {
    const t0 = Date.now();
    api
      .healthz()
      .then((res) => {
        this.setData({
          backendOk: true,
          healthChecked: true,
          healthMs: Date.now() - t0,
        });
        if (res && res.credentials_ok === false) {
          wx.showModal({
            title: '后端缺少 API Key',
            content:
              '服务起来了，但没有配置 DEEPSEEK_API_KEY，点「给我建议」会失败。\n' +
              '请在 credentials.env 里填入 Key 后重启后端。',
            showCancel: false,
          });
        }
      })
      .catch(() => {
        this.setData({
          backendOk: false,
          healthChecked: true,
          healthMs: Date.now() - t0,
        });
      });
  },

  recheck() {
    wx.showLoading({ title: '检测中', mask: true });
    const t0 = Date.now();
    api
      .healthz()
      .then((res) => {
        wx.hideLoading();
        // 连通但凭据缺失时不能说"连接正常"
        if (res && res.credentials_ok === false) {
          this.setData({ backendOk: true, healthChecked: true, healthMs: Date.now() - t0 });
          wx.showToast({ title: '连通但缺 API Key', icon: 'none', duration: 3000 });
          return;
        }
        this.setData({
          backendOk: true,
          healthChecked: true,
          healthMs: Date.now() - t0,
        });
        wx.showToast({ title: `连接正常 ${Date.now() - t0}ms`, icon: 'success' });
      })
      .catch(() => {
        wx.hideLoading();
        this.setData({
          backendOk: false,
          healthChecked: true,
          healthMs: Date.now() - t0,
        });
        wx.showToast({ title: '仍然连不上', icon: 'none' });
      });
  },

  copyApiBase() {
    wx.setClipboardData({
      data: this.data.apiBase,
      success: () => wx.showToast({ title: '已复制接口地址', icon: 'none' }),
    });
  },

  // ------------------------------------------------------------
  // 输入与示例
  // ------------------------------------------------------------
  onInput(e) {
    this.setData({ text: e.detail.value });
  },

  /**
   * 点示例填入。
   * 关键：若输入框已有内容，不覆盖，改为追加——原来直接覆盖会静默清空用户手打的内容。
   */
  useExample(e) {
    const picked = e.currentTarget.dataset.text || '';
    if (!picked) return;

    const list = this.data.examples || [];
    const idx = Number(e.currentTarget.dataset.index);

    // 靠下标判断"这句加过了"。
    // 不能用"全文 === 示例"判断：第一次追加后全文已变，第二次点同一条会再追加一遍。
    const used = this.data.usedExamples || [];
    if (Number.isInteger(idx) && idx >= 0 && used.indexOf(idx) >= 0) {
      wx.showToast({ title: '这句已经加过了', icon: 'none' });
      return;
    }
    // 下标不可用时的兜底：全文里已经含有去时段后的示例内容
    const stripped = picked.replace(/^(早上|中午|晚上|夜宵|下午|凌晨)/, '');
    if (!Number.isInteger(idx) && stripped && (this.data.text || '').indexOf(stripped) >= 0) {
      wx.showToast({ title: '这句已经加过了', icon: 'none' });
      return;
    }

    const current = (this.data.text || '').trim();
    let nextText;
    if (!current) {
      nextText = picked;
    } else {
      // 续写：去掉示例开头的时段词，再按中文习惯补连接词，避免两句直接黏在一起
      const needsComma = !/[，。！？、；,]$/.test(current);
      nextText = current + (needsComma ? '，还' : '还') + stripped;
    }

    if (nextText.length > MAX_LEN) {
      wx.showToast({ title: `再加就超过 ${MAX_LEN} 字了`, icon: 'none' });
      return;
    }

    const nextUsed =
      Number.isInteger(idx) && idx >= 0 ? used.concat([idx]) : used;
    this.setData({ text: nextText, inputFocus: true, usedExamples: nextUsed });
  },

  clearText() {
    if (!this.data.text) return;
    wx.showModal({
      title: '清空描述',
      content: '确定要清空已经写的内容吗？',
      success: (r) => {
        // 清空后示例也回到"未使用"，可以重新点
        if (r.confirm) this.setData({ text: '', usedExamples: [] });
      },
    });
  },

  onTextareaBlur() {
    // 失焦后复位，保证下次点示例能再次触发聚焦
    if (this.data.inputFocus) this.setData({ inputFocus: false });
  },

  // ------------------------------------------------------------
  // 提交
  // ------------------------------------------------------------
  submit() {
    const text = (this.data.text || '').trim();
    if (!text) {
      wx.showToast({ title: '先说说吃了什么', icon: 'none' });
      return;
    }
    if (this.data.loading) return;

    // 后端连不上就别跳了：否则用户要盯着结果页等 60 秒超时
    if (this.data.healthChecked && !this.data.backendOk) {
      wx.showModal({
        title: '后端连不上',
        content:
          '现在请求 ' + this.data.apiBase + ' 没有响应，先按上面的提示排查，' +
          '或点「重新检测」。',
        showCancel: false,
      });
      return;
    }

    const constitution = this.currentConstitution().id;
    this.setData({ loading: true });
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
