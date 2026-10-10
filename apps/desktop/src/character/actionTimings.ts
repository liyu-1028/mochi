/**
 * 语义动作时长基线（渲染无关）：调度层（reflexRules 默认窗口）与
 * 引擎侧包络（live2d/stateMachine 的 BODY_ACTION_ENVELOPES）共用，
 * 避免渲染无关模块反向依赖具体渲染实现。
 */
/** wink（眨眨眼）包络时长 */
export const WINK_DURATION_MS = 700;
/** doze（打哈欠/犯困）包络时长 */
export const DOZE_DURATION_MS = 1600;
