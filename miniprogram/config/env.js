/**
 * 环境配置 —— 部署/换网络时只需要改这个文件。
 *
 * ⚠️ 局域网 IP 会变（DHCP 重新分配、换 WiFi 都会变）。
 * 手机真机预览报「request:fail」时，第一件事就是回来核对这里的 IP。
 *
 * 查看当前电脑 IP（PowerShell）：
 *   Get-NetIPAddress -AddressFamily IPv4 |
 *     Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' }
 */
const ENV = {
  // 开发者工具里用这个就行
  API_BASE_URL: 'http://10.64.77.122:8000',

  // 真机预览时把上面的地址改成电脑的局域网 IP，例如：
  //   API_BASE_URL: 'http://192.168.1.5:8000',
  // 前提：后端用 --host 0.0.0.0 启动，且手机与电脑在同一 WiFi。

  // 双 Agent 串行大约 12-18 秒，这里给足余量
  TIMEOUT_MS: 60000,

  // 同一个体质 + 相同口述时，短时间内不重复请求（省调用费）
  CACHE_TTL_MS: 10 * 60 * 1000,
};

module.exports = ENV;
