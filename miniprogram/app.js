// 全局逻辑。本地 demo 阶段刻意保持极简：
// 没有登录、没有服务端用户体系，体质只存在本机 Storage 里。
App({
  globalData: {
    // 后端地址与超时，改 config/env.js
    env: require('./config/env.js'),
  },

  onLaunch() {
    const env = this.globalData.env;
    console.log('[tea-advisor] API_BASE_URL =', env.API_BASE_URL);
    if (env.API_BASE_URL.indexOf('127.0.0.1') === 0) {
      console.warn(
        '[tea-advisor] 当前指向 127.0.0.1：开发者工具里能用，但真机预览时手机连不上，' +
          '需要在 miniprogram/config/env.js 里改成电脑的局域网 IP。'
      );
    }
  },

  onError(err) {
    console.error('[tea-advisor] 未捕获错误', err);
  },
});
