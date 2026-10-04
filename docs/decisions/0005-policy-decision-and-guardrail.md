# 0005 策略判定与拦截点

## 背景（Context）

0.1.0 的授权只存在于具体执行器内部：`CalculatorToolExecutor` 用允许列表检查工具名与处理函数。这能保护计算工具，但没有任何机制让外层表达“本次运行允许出现哪些能力”，也没有 `PolicyTriggered`、`GuardrailBlocked` 这两个安全审计事件的发射方。

同时，审批（`ASK`）的语义尚未确定：谁负责恢复执行、批准与拒绝分别产生什么结果都还没有设计。

## 决策（Decision）

- 在 `core/policy` 定义判定语义 `PolicyVerdict`（`ALLOW`/`DENY`/`ASK`）、判定结果 `PolicyDecision`、判定输入 `ToolPolicyRequest` 与规则契约 `ToolPolicyRule`；`PolicyEngine` 按注册顺序评估规则，第一条非 `ALLOW` 判定生效，没有规则介入时为默认允许。
- 拦截点在运行器的工具调用边界：`ToolCallStart` 之后、调用执行器之前判定。`DENY` 与 `ASK` 都不调用执行器。
- 每次非默认判定发出 `PolicyTriggered`（含规则名、处置、理由）；`DENY` 与 `ASK` 额外发出 `GuardrailBlocked`（含规则名、调用 ID、工具名、理由）。
- 拦截不中断整次执行：运行器向模型返回 `is_error=True` 的 `ToolResult`，模型可以据此换用其他方式或向用户说明。这与“工具自身返回错误结果”的处理保持一致。
- `ASK` 当前与 `DENY` 一样被拦截，理由文本明确说明“尚未实现审批流程”。核心层不提供空接口或占位状态，等审批语义确定后再接入。
- 策略判定不替代执行器自身的校验与授权；两者各自完成自己那部分检查，`CalculatorToolExecutor` 的允许列表保持不变。

## 理由（Reason）

- 把“是否允许”和“如何执行”分开，运行器只依赖判定结果，规则可以由外层或基础设施提供，Core 不引入具体策略或用户界面。
- 拦截是受控结果而不是异常，避免一次被拒绝的调用直接终止整次任务；同时审计事件已经记录完整信息。
- 明确记录 `ASK` 暂时被拦截，比提供一个永远返回“等待审批”却无人恢复的路径更安全。

## 备选方案（Alternative）

- 只在执行器内部判定：无法表达运行级策略，事件也缺少统一的判定输入。
- 把 `ASK` 映射为 `WAITING_APPROVAL` 状态并阻塞：需要先确定审批语义与恢复执行的责任方，否则运行会永久挂起。
- 拦截时抛出异常终止运行：语义简单，但把“模型换一种做法”这种正常情况变成了失败。
- 让策略规则读取工具参数做内容检查：更强的能力，但也更容易把参数取值泄漏到事件与日志；本阶段规则只匹配工具名。

## 影响（Consequence）

- `AgentRunner` 新增可选参数 `policy`；默认 `PolicyEngine()` 没有任何规则，因此不传策略时行为与之前一致（全部允许、不产生策略事件）。
- `PolicyTriggered.reason` 与 `GuardrailBlocked.reason` 来自规则，规则必须避免写入参数取值或密钥。
- `GuardrailBlocked` 新增 `name` 字段，`PolicyTriggered` 新增 `reason` 字段。
- 现有计算工具的执行器保持不变；策略是额外的外层约束，不是它的替代品。
- 真正的权限系统、审批等待与 `WAITING_APPROVAL` 状态仍需单独设计。
