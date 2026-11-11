#!/usr/bin/env python3
"""backtest-lint — lint.py v0.1.2 (Phase 6a)

AST 静态检查：在回测跑起来之前拦截代码级作弊（考卷 = corpus v1.2.7 的
18 个 lint 样本：15 植病 + 3 干净，答案卷 tests/corpus/expected_results.json）。

v0.1.1（Gate C M-1/m-1 修复）：滞后判定跟成交时点走（仓位表达式内所有
价格读被 shift(k>=1) 挡住即 T+1 干净，shift 位置不限）；102 evidence
只陈述仓位侧实际读到的 bar-t 价格列。

v0.1.2：`gate` 对读不动/结构不对的语料不再抛裸 traceback，改为 stdout 发
JSON 错误信封、exit 2（输入错误）。之前损坏的 expected_results.json 会
以 Traceback 逃逸且 stdout 为空，正是 agent 无法分类的那种失败。

规则语义（与答案卷 desc 一一对应）：
  lint.101  same-bar execution   —— bar t 信息做出的仓位 × bar t 的
             close-to-close 收益（决策与成交同 bar）。含 helper 封装与
             循环形态（循环体读 .iloc[i] 当期价 → 当期收益）。
             滞后判定跟成交时点走：仓位表达式内所有价格读（含经
             df 列 / helper 传递）都被 shift(k>=1) 挡住即视为 T+1
             干净——shift 写在哪一层不限（比较式内部两侧、helper
             return 后缀、np.where 内层均可）。
  lint.102  look-ahead           —— 未滞后仓位 × open-to-open 收益
             （bar t close 的信息被用于 bar t open 的成交）。
             evidence 只陈述仓位侧实际读到的 bar-t 价格列：close
             仅在确有未被 shift(k>=1) 挡住的 close 读时提及。
  lint.103  centered window      —— rolling(center=True)，含藏进
             **kwargs 透传（helper 定义 .rolling(**kw)，调用点传
             center=True）与 .apply 形态。
  lint.104  future leak          —— shift(负数)；序列末端标量
             （[-1] 类索引）或尾部窗口统计量（iloc[-N:] + 归约）
             回流进信号/仓位/pnl 链。
  lint.105  vacuous gates        —— 有效断言计数为 0（无断言 / 全被
             注释 / 恒真断言）。恒真目录：常量真值、is (not) None、
             双常量比较。命中 101-104 任一执行级规则时不重复报告
             （考卷单病隔离设计；执行级病灶优先，真实代码两者并存
             时 105 静默——限制见下）。

诚实限制（v0.1.0）：
  - 数据流是名字级的列追踪；pandas 链式改名未完全建模。
  - shift(不可解析变量) 按已滞后处理（防误报方向，可能漏报）。
  - [-1] 类末端访问只在其流入 signal/position/pnl 链时报告（末端
    汇报用途如 final_nav = eq.iloc[-1] 不报告）。
  - 101/102 的收益源只识别 close→101、open→102；high/low 源不判。
  - 循环检测覆盖 append-to-list → [0]+ 拼接 → 同 bar 乘积形态。
  - 无 df["col"] 形态的文件 → cannot_determine（不编造确定性）。

CLI：
  check <path>            单文件或目录 → JSON（findings / caught / rules）
  gate --corpus DIR       对答案卷 18 样本评分，exit 0 iff 全过
  selftest                正控+反控断言集
exit 约定：0 = 正常运行（findings 是产品不是错误）；2 = 输入错误
（文件缺失 / 语法错误），stdout 为含 error 的 JSON；gate 失败 exit 1。
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

VERSION = "0.1.2"
PRICE_COLS = {"open", "high", "low", "close", "adjclose", "price"}
POS_NAMES = ("position", "pos", "exposure", "weight", "holding")
SIGNAL_HINTS = ("signal", "label", "entry")
PNL_HINTS = ("pnl", "strat_ret", "strategy_ret", "portfolio_ret")
RET_ATTRS = {"pct_change", "diff"}
REDUCERS = {"std", "mean", "var", "sum", "max", "min", "median",
            "quantile", "skew", "kurt", "sem"}
TRANSPARENT_SUFFIX = {"fillna", "astype", "clip", "convert_dtypes",
                      "replace", "sort_index", "reset_index", "abs"}


# ── flags ────────────────────────────────────────────────────────────
class Flags:
    """列/变量定义的表达式特征（可继承合并）。"""

    def __init__(self):
        self.reads_price = False     # 读取价格列（当期或滞后均可）
        self.bar_t_cols = set()      # 未被 shift(k>=1) 挡住的 bar-t 价格列
        self.neg_shift = False       # 树中任何 .shift(k<0)
        self.center = False          # rolling(center=True)（含透传）
        self.neg_index = False       # [-1] 类末端常量下标
        self.tail_reduce = False     # iloc[-N:] + 归约
        self.is_ret = False          # 含 pct_change/diff
        self.ret_source = None       # 若表达式即 <价格列>.pct_change()：列名
        self.deps = set()            # 引用的列名/变量名（可达性图）

    def merge(self, other):
        for k in ("reads_price", "neg_shift", "center",
                  "neg_index", "tail_reduce", "is_ret"):
            if getattr(other, k):
                setattr(self, k, True)
        if self.ret_source is None and other.ret_source is not None:
            self.ret_source = other.ret_source
        self.deps |= other.deps
        self.bar_t_cols |= other.bar_t_cols

    def merge_lagged(self, other):
        """合并被 shift(k>=1) 保护的子树：吞掉 bar-t 价格读（该子树在
        bar t 的取值只依赖 <=t-1 的信息），其余特征照常传播（center /
        负 shift / 末端标量等照报——滞后不洗白居中窗与未来数据）。"""
        for k in ("reads_price", "neg_shift", "center",
                  "neg_index", "tail_reduce", "is_ret"):
            if getattr(other, k):
                setattr(self, k, True)
        if self.ret_source is None and other.ret_source is not None:
            self.ret_source = other.ret_source
        self.deps |= other.deps


# ── constant resolution ──────────────────────────────────────────────
def resolve_const(node, consts):
    """解析简单常量：数字字面量或此前赋值的局部常量（int/float）。"""
    if isinstance(node, ast.Constant) and isinstance(
            node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = resolve_const(node.operand, consts)
        return -v if v is not None else None
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    return None


# ── helper indexing（跨函数：**kwargs 透传 + 体内静态特征） ──────────
def index_helpers(tree):
    helpers = {}
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        params = {a.arg for a in fn.args.args}
        params |= {a.arg for a in fn.args.posonlyargs}
        kw_names = {a.arg for a in fn.args.kwonlyargs}
        if fn.args.kwarg is not None:
            kw_names.add(fn.args.kwarg.arg)
        body = Flags()
        reads_args = False
        passthrough = False
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and node.id in params:
                if isinstance(node.ctx, ast.Load):
                    reads_args = True
            if isinstance(node, ast.Call) and isinstance(
                    node.func, ast.Attribute) and node.func.attr == "rolling":
                for kw in node.keywords:
                    if kw.arg is None and isinstance(kw.value, ast.Name) \
                            and kw.value.id in kw_names:
                        passthrough = True
                    if kw.arg == "center":
                        v = kw.value
                        if isinstance(v, ast.Constant) and v.value:
                            body.center = True
            if isinstance(node, ast.Call) and isinstance(
                    node.func, ast.Attribute) \
                    and node.func.attr == "shift":
                for a in node.args:
                    v = resolve_const(a, consts={})
                    if v is not None and v < 0:
                        body.neg_shift = True
            if isinstance(node, ast.Subscript):
                sl = node.slice
                if isinstance(sl, ast.UnaryOp) and isinstance(
                        sl.op, ast.USub):
                    body.neg_index = True
            if isinstance(node, ast.Call) and isinstance(
                    node.func, ast.Attribute) \
                    and node.func.attr in RET_ATTRS:
                body.is_ret = True
        # 所有读取入参的 return 是否都带 suffix shift(k>=1 / 不可解析)
        # —— 是则该 helper 的调用结果视为已滞后（入参的 bar-t 价格读
        # 被 return 的滞后挡住；对入参的读取按体内局部变量传递展开）
        # helper 体内局部变量 → 表达式读取的名字
        local_reads = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                local_reads[node.targets[0].id] = {
                    n2.id for n2 in ast.walk(node.value)
                    if isinstance(n2, ast.Name)}
        returns = [n for n in ast.walk(fn)
                   if isinstance(n, ast.Return) and n.value is not None]

        def _reads_params(r):
            seen, stack = set(), [n2.id for n2 in ast.walk(r.value)
                                  if isinstance(n2, ast.Name)]
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                stack.extend(local_reads.get(cur, ()))
            return bool(seen & params)

        eff = [r for r in returns if _reads_params(r)]

        def _shifted(k):
            return k is None or (isinstance(k, (int, float)) and k >= 1)

        returns_shifted = bool(eff) and all(
            _shifted(suffix_shift(r.value, {})) for r in eff)
        helpers[fn.name] = {
            "params": params, "reads_args": reads_args,
            "passthrough": passthrough, "flags": body,
            "returns_shifted": returns_shifted,
        }
    return helpers


# ── expression scanner ───────────────────────────────────────────────
def suffix_shift(expr, consts):
    """顶层链上的 shift 期数：k>=1 / 0（无）/ None（不可解析，按滞后）。"""
    node = expr
    while True:
        if isinstance(node, ast.Call) and isinstance(node.func,
                                                     ast.Attribute):
            attr = node.func.attr
            if attr == "shift":
                arg = node.args[0] if node.args else next(
                    (kw.value for kw in node.keywords
                     if kw.arg == "periods"), None)
                v = resolve_const(arg, consts)
                return v  # int 或 None
            if attr in TRANSPARENT_SUFFIX:
                node = node.func.value
                continue
            return 0
        return 0


def scan_expr(node, consts, helpers, coldefs, vardefs, flags,
              in_reducer_receiver=False):
    """递归扫描表达式，累计特征。coldefs/vardefs 按已定义项继承。"""
    if node is None:
        return
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute):
            attr = f.attr
            if attr == "shift":
                arg = node.args[0] if node.args else next(
                    (kw.value for kw in node.keywords
                     if kw.arg == "periods"), None)
                v = resolve_const(arg, consts)
                if v is not None and v < 0:
                    flags.neg_shift = True
                    scan_expr(f.value, consts, helpers, coldefs, vardefs,
                              flags)
                elif v is None or v >= 1:
                    # shift(k>=1 / 不可解析)：receiver 的 bar-t 价格读
                    # 被挡住——滞后判定跟成交时点走，不跟定义后缀走
                    tf = Flags()
                    scan_expr(f.value, consts, helpers, coldefs, vardefs,
                              tf)
                    flags.merge_lagged(tf)
                else:  # shift(0)：显式 identity，不保护
                    scan_expr(f.value, consts, helpers, coldefs, vardefs,
                              flags)
                for a in node.args:
                    scan_expr(a, consts, helpers, coldefs, vardefs, flags)
                for kw in node.keywords:
                    scan_expr(kw.value, consts, helpers, coldefs, vardefs,
                              flags)
                return
            elif attr in RET_ATTRS:
                flags.is_ret = True
                # <价格列>.pct_change() → 记录收益源
                base = f.value
                if isinstance(base, ast.Subscript) and isinstance(
                        base.value, ast.Name) and isinstance(
                        base.slice, ast.Constant) \
                        and isinstance(base.slice.value, str) \
                        and base.slice.value in PRICE_COLS:
                    flags.ret_source = base.slice.value
            elif attr in REDUCERS:
                scan_expr(f.value, consts, helpers, coldefs, vardefs,
                          flags, in_reducer_receiver=True)
                for a in node.args:
                    scan_expr(a, consts, helpers, coldefs, vardefs, flags)
                for kw in node.keywords:
                    scan_expr(kw.value, consts, helpers, coldefs,
                              vardefs, flags)
                return
            if attr == "rolling":
                for kw in node.keywords:
                    if kw.arg == "center" and isinstance(
                            kw.value, ast.Constant) and kw.value.value:
                        flags.center = True
                # pandas 签名 rolling(window, min_periods, center, ...)
                # 位置传参第 3 位即 center
                if len(node.args) >= 3 and isinstance(
                        node.args[2], ast.Constant) and node.args[2].value:
                    flags.center = True
            scan_expr(f.value, consts, helpers, coldefs, vardefs, flags)
            for a in node.args:
                scan_expr(a, consts, helpers, coldefs, vardefs, flags)
            for kw in node.keywords:
                scan_expr(kw.value, consts, helpers, coldefs, vardefs,
                          flags)
            return
        if isinstance(f, ast.Name) and f.id in helpers:
            h = helpers[f.id]
            flags.merge(h["flags"])
            if h["reads_args"]:
                for a in node.args:
                    af = Flags()
                    scan_expr(a, consts, helpers, coldefs, vardefs, af)
                    if h["returns_shifted"]:
                        # helper return 带 shift(k>=1)：入参的 bar-t
                        # 价格读被 return 的滞后挡住
                        flags.merge_lagged(af)
                    else:
                        flags.merge(af)
            if h["passthrough"]:
                for kw in node.keywords:
                    if kw.arg == "center" and isinstance(
                            kw.value, ast.Constant) and kw.value.value:
                        flags.center = True
                    else:
                        scan_expr(kw.value, consts, helpers, coldefs,
                                  vardefs, flags)
            return
        # 其他调用：扫参数
        for a in node.args:
            scan_expr(a, consts, helpers, coldefs, vardefs, flags)
        for kw in node.keywords:
            scan_expr(kw.value, consts, helpers, coldefs, vardefs, flags)
        return
    if isinstance(node, ast.Subscript):
        sl = node.slice
        if isinstance(sl, ast.UnaryOp) and isinstance(sl.op, ast.USub) \
                and isinstance(sl.operand, ast.Constant):
            if in_reducer_receiver:
                flags.tail_reduce = True
            else:
                flags.neg_index = True
        elif isinstance(sl, ast.Slice):
            if sl.lower is not None and isinstance(
                    sl.lower, ast.UnaryOp) and isinstance(
                    sl.lower.op, ast.USub):
                if in_reducer_receiver:
                    flags.tail_reduce = True
                # 非归约下的尾部切片不单独定罪
        # df["col"] 列引用：继承 + 价格读
        base = node.value
        if isinstance(base, ast.Name) and isinstance(sl, ast.Constant) \
                and isinstance(sl.value, str):
            col = sl.value
            if col in PRICE_COLS:
                flags.reads_price = True
                flags.bar_t_cols.add(col)
            flags.deps.add(col)
            if col in coldefs:
                flags.merge(coldefs[col])
        elif isinstance(base, ast.Attribute) and base.attr == "iloc":
            scan_expr(base.value, consts, helpers, coldefs, vardefs, flags)
            return
        elif isinstance(base, ast.Attribute):  # x.values[-1] 等
            scan_expr(base.value, consts, helpers, coldefs, vardefs, flags)
            return
        else:
            scan_expr(base, consts, helpers, coldefs, vardefs, flags)
        return
    if isinstance(node, ast.Name):
        if node.id in vardefs:
            flags.merge(vardefs[node.id])
            flags.deps.add(node.id)
        if node.id in consts:
            pass
        return
    if isinstance(node, ast.Attribute):
        scan_expr(node.value, consts, helpers, coldefs, vardefs, flags)
        return
    if isinstance(node, ast.Compare):
        scan_expr(node.left, consts, helpers, coldefs, vardefs, flags)
        for c in node.comparators:
            scan_expr(c, consts, helpers, coldefs, vardefs, flags)
        return
    if isinstance(node, ast.BinOp):
        scan_expr(node.left, consts, helpers, coldefs, vardefs, flags)
        scan_expr(node.right, consts, helpers, coldefs, vardefs, flags)
        return
    if isinstance(node, ast.UnaryOp):
        scan_expr(node.operand, consts, helpers, coldefs, vardefs, flags)
        return
    if isinstance(node, ast.BoolOp):
        for v in node.values:
            scan_expr(v, consts, helpers, coldefs, vardefs, flags)
        return
    if isinstance(node, ast.IfExp):
        for v in (node.body, node.orelse, node.test):
            scan_expr(v, consts, helpers, coldefs, vardefs, flags)
        return
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for e in node.elts:
            scan_expr(e, consts, helpers, coldefs, vardefs, flags)
        return
    # 其余节点类型（常量等）：不产生特征


# ── vacuous assert 判定 ──────────────────────────────────────────────
def is_vacuous_assert(test):
    if isinstance(test, ast.Constant):
        return bool(test.value)
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return is_vacuous_assert(test.operand)
    if isinstance(test, ast.Compare):
        if isinstance(test.ops[0], (ast.Is, ast.IsNot)):
            if isinstance(test.comparators[0], ast.Constant) \
                    and test.comparators[0].value is None:
                return True
        if isinstance(test.left, ast.Constant) and isinstance(
                test.comparators[0], ast.Constant):
            return True
    return False


# ── per-file analysis ────────────────────────────────────────────────
def analyze_source(src, filename="<source>"):
    """返回 {strategy_like, findings: [{rule, tier, evidence}]}。"""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise SyntaxError(f"{filename}: {e.msg} (line {e.lineno})")
    helpers = index_helpers(tree)
    findings = []

    # 文件级：有效断言计数（lint.105）
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    meaningful = [a for a in asserts if not is_vacuous_assert(a.test)]

    # 找 df 形态函数（含 df["col"] 下标的函数）
    strategy_fns = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(fn):
            if isinstance(node, ast.Subscript) and isinstance(
                    node.value, ast.Name) and isinstance(
                    node.slice, ast.Constant) \
                    and isinstance(node.slice.value, str):
                strategy_fns.append(fn)
                break

    if not strategy_fns:
        return {"strategy_like": False, "findings": []}

    # lint.105：策略文件 + 零有效断言
    if not meaningful:
        vac = len(asserts) - len(meaningful)
        findings.append({
            "rule": "lint.105", "tier": "verified",
            "evidence": f"{len(asserts)} assert statement(s) in file, "
                        f"{vac} vacuous, 0 meaningful gates "
                        f"(NaN/conservation/position-domain/warmup)"})

    all_center_defs = []   # (name, kind) 带 center 特征的定义
    all_future_defs = []   # 带 neg_index/tail_reduce 的定义
    any_neg_shift = [False, None]

    for fn in strategy_fns:
        consts, coldefs, vardefs = {}, {}, {}
        pnl_cols, pos_cols = set(), set()
        appends = {}        # list 名 → 循环信息
        for stmt in fn.body:
            for node in ast.walk(stmt):
                # 常量捕获（lookback = 20）
                if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                        and isinstance(node.targets[0], ast.Name):
                    v = resolve_const(node.value, consts)
                    if v is not None:
                        consts[node.targets[0].id] = v
            # 赋值：列 / 变量
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                tgt, expr = stmt.targets[0], stmt.value
                fl = Flags()
                scan_expr(expr, consts, helpers, coldefs, vardefs, fl)
                if isinstance(tgt, ast.Subscript) and isinstance(
                        tgt.value, ast.Name) and isinstance(
                        tgt.slice, ast.Constant) \
                        and isinstance(tgt.slice.value, str):
                    col = tgt.slice.value
                    coldefs[col] = fl
                    if any(h in col for h in PNL_HINTS):
                        pnl_cols.add(col)
                    if any(p in col for p in POS_NAMES):
                        pos_cols.add(col)
                    if fl.center:
                        all_center_defs.append((col, "col"))
                    if fl.neg_index or fl.tail_reduce:
                        all_future_defs.append((col, "col"))
                    # pnl 乘积模式：position-ish × ret-ish
                    if isinstance(expr, ast.BinOp) and isinstance(
                            expr.op, ast.Mult):
                        _check_product(expr, col, coldefs, consts,
                                       helpers, vardefs, fl, findings,
                                       pos_cols, pnl_cols)
                elif isinstance(tgt, ast.Name):
                    vardefs[tgt.id] = fl
                    if fl.center:
                        all_center_defs.append((tgt.id, "var"))
                    if fl.neg_index or fl.tail_reduce:
                        all_future_defs.append((tgt.id, "var"))
                    if any(p in tgt.id for p in POS_NAMES):
                        pass
            # 循环：当期价读 + append
            if isinstance(stmt, ast.For):
                _scan_loop(stmt, consts, appends)
        # 循环形态 101：append 列表 → position 列 → × close ret
        _eval_loops(fn, appends, coldefs, consts, helpers, vardefs,
                    findings)
        # 文件级 neg_shift（任何策略函数内）
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(
                    node.func, ast.Attribute) \
                    and node.func.attr == "shift":
                arg = node.args[0] if node.args else next(
                    (kw.value for kw in node.keywords
                     if kw.arg == "periods"), None)
                v = resolve_const(arg, consts)
                if v is not None and v < 0:
                    any_neg_shift[0] = True
                    if any_neg_shift[1] is None:
                        any_neg_shift[1] = f".shift({int(v)})"

    # lint.104：负 shift（不限链，语法确定性；含 helper 体内经调用合并的）
    neg_shift_defs = []
    for fn in strategy_fns:
        consts, coldefs, vardefs = {}, {}, {}
        for stmt in fn.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                fl = Flags()
                scan_expr(stmt.value, consts, helpers, coldefs, vardefs,
                          fl)
                if fl.neg_shift:
                    neg_shift_defs.append(stmt)
    if any_neg_shift[0]:
        findings.append({
            "rule": "lint.104", "tier": "verified",
            "evidence": f"negative shift pulls future bars back: "
                        f"{any_neg_shift[1]}"})
    elif neg_shift_defs:
        findings.append({
            "rule": "lint.104", "tier": "verified",
            "evidence": "negative shift pulls future bars back "
                        "(inside helper called from strategy function)"})

    # 可达性：center / 末端标量 定义是否流入 pos/pnl 链
    if all_center_defs or all_future_defs:
        # 汇总全部定义图（跨函数简化：文件级合并）
        defs = {}
        for fn in strategy_fns:
            pass  # 图在各函数内已建；此处用收集期 deps 重建
        # 重建：重扫一遍收集 def→deps
        graph = {}
        terminals = set()
        for fn in strategy_fns:
            consts, coldefs, vardefs = {}, {}, {}
            for stmt in fn.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    tgt, expr = stmt.targets[0], stmt.value
                    fl = Flags()
                    scan_expr(expr, consts, helpers, coldefs, vardefs, fl)
                    if isinstance(tgt, ast.Subscript) and isinstance(
                            tgt.slice, ast.Constant) \
                            and isinstance(tgt.slice.value, str):
                        col = tgt.slice.value
                        graph.setdefault(col, set()).update(fl.deps)
                        if any(p in col for p in POS_NAMES) or any(
                                h in col for h in PNL_HINTS):
                            terminals.add(col)
                    elif isinstance(tgt, ast.Name):
                        graph.setdefault(tgt.id, set()).update(fl.deps)
        reached = _ancestors(terminals, graph)
        for name, kind in all_center_defs:
            if name in reached:
                findings.append({
                    "rule": "lint.103", "tier": "verified",
                    "evidence": f"rolling(center=True) reaches "
                                f"position/pnl via '{name}'"})
                break
        for name, kind in all_future_defs:
            if name in reached:
                findings.append({
                    "rule": "lint.104", "tier": "verified",
                    "evidence": f"end-of-series anchor "
                                f"([-1] index / tail-window stat) flows "
                                f"into signal/position/pnl via '{name}'"})
                break

    # 去重（同规则保留首个证据）
    seen, uniq = set(), []
    for f in findings:
        if f["rule"] not in seen:
            seen.add(f["rule"])
            uniq.append(f)
    # 105 抑制规则：命中任一执行级病灶（101-104）时不重复报告
    if "lint.105" in seen and seen - {"lint.105"}:
        uniq = [f for f in uniq if f["rule"] != "lint.105"]
    order = {"lint.101": 1, "lint.102": 2, "lint.103": 3,
             "lint.104": 4, "lint.105": 5}
    uniq.sort(key=lambda f: order[f["rule"]])
    return {"strategy_like": True, "findings": uniq}


def _check_product(expr, col, coldefs, consts, helpers, vardefs, fl,
                   findings, pos_cols, pnl_cols):
    """pnl = position-ish × ret-ish：101（close 源）/ 102（open 源）。"""
    a, b = expr.left, expr.right

    def flags_of(node):
        f = Flags()
        scan_expr(node, consts, helpers, coldefs, vardefs, f)
        return f

    def name_of(node):
        # 剥掉透明后缀（fillna/astype/…）与 .shift(k)：仓位名可见即可
        # （滞后与否由 flags 的 bar_t_cols 判定，不由名字形态判定）
        while isinstance(node, ast.Call) and isinstance(
                node.func, ast.Attribute) and (
                node.func.attr in TRANSPARENT_SUFFIX
                or node.func.attr == "shift"):
            node = node.func.value
        if isinstance(node, ast.Subscript) and isinstance(
                node.slice, ast.Constant) and isinstance(
                node.slice.value, str):
            return node.slice.value
        if isinstance(node, ast.Name):
            return node.id
        return None

    fa, fb = flags_of(a), flags_of(b)
    # 判定哪一侧是仓位/信号、哪一侧是收益
    pos_side, ret_side = None, None
    for side, f in ((a, fa), (b, fb)):
        nm = name_of(side)
        if nm and (any(p in nm for p in POS_NAMES)
                   or any(s in nm for s in SIGNAL_HINTS)):
            pos_side = (nm, f)
    for side, f in ((a, fa), (b, fb)):
        if f.is_ret and (pos_side is None or name_of(side) != pos_side[0]):
            ret_side = f
            break
    if pos_side is None or ret_side is None:
        return
    nm, pf = pos_side
    # 定罪条件（v0.1.1）：仓位侧存在未被 shift(k>=1) 挡住的 bar-t 价格读
    # （经 df 列 / 变量 / helper 传递同样计入）。全部被挡住 = T+1 干净；
    # 完全不读价格 = 不定罪（沿用 v0.1.0 方向）。
    if not pf.bar_t_cols:
        return
    cols_str = "/".join(sorted(pf.bar_t_cols))
    src = ret_side.ret_source
    if src == "close":
        findings.append({
            "rule": "lint.101", "tier": "verified",
            "evidence": f"pnl col '{col}': '{nm}' is unshifted and "
                        f"reads bar-t {cols_str} info, multiplied by "
                        f"same-bar close-to-close return"})
    elif src == "open":
        if "close" in pf.bar_t_cols:
            ev = (f"pnl col '{col}': '{nm}' is unshifted and reads "
                  f"bar-t close info, multiplied by open-to-open return "
                  f"(bar-t close is unknown at bar-t open)")
        else:
            ev = (f"pnl col '{col}': '{nm}' is unshifted and reads "
                  f"bar-t {cols_str} info, multiplied by open-to-open "
                  f"return (a decision on bar-t {cols_str} cannot "
                  f"capture a return concluding at bar-t open)")
        findings.append({"rule": "lint.102", "tier": "verified",
                         "evidence": ev})


def _scan_loop(stmt, consts, appends):
    """收集循环：当期 .iloc[loopvar] 价格读 + append 的列表名。"""
    tvar = stmt.target.id if isinstance(stmt.target, ast.Name) else None
    if tvar is None:
        return
    current_read, append_lists = False, []
    for node in ast.walk(stmt):
        if isinstance(node, ast.Call) and isinstance(node.func,
                                                     ast.Attribute) \
                and node.func.attr == "append":
            v = node.func.value
            if isinstance(v, ast.Name):
                append_lists.append(v.id)
        if isinstance(node, ast.Subscript):
            base = node.value
            if isinstance(base, ast.Attribute) and base.attr == "iloc" \
                    and isinstance(node.slice, ast.Name) \
                    and node.slice.id == tvar:
                inner = base.value
                if isinstance(inner, ast.Subscript) and isinstance(
                        inner.slice, ast.Constant) \
                        and inner.slice.value in PRICE_COLS:
                    current_read = True
    for lst in append_lists:
        appends[lst] = {"current_read": current_read}


def _eval_loops(fn, appends, coldefs, consts, helpers, vardefs,
                findings):
    """循环建仓列表 → position 列 → × 同 bar close ret → 101。"""
    for lst, info in appends.items():
        if not info["current_read"]:
            continue
        for col, fl in coldefs.items():
            if not any(p in col for p in POS_NAMES):
                continue
            if lst in fl.deps:  # position 列引用了该列表
                # 该 position 列是否与 close 源收益相乘
                for pcol, pfl in coldefs.items():
                    if pfl.is_ret and pfl.ret_source == "close" \
                            and col in pfl.deps:
                        findings.append({
                            "rule": "lint.101", "tier": "verified",
                            "evidence": f"loop decides on bar-i price "
                                        f"(.iloc[i] read) into list "
                                        f"'{lst}' → column '{col}', "
                                        f"multiplied by same-bar "
                                        f"close-to-close '{pcol}'"})
                        return


def _ancestors(terminals, graph):
    """终端（position/pnl 列）传递依赖的全部定义名。
    边方向：graph[X] = X 的表达式引用的名字（X 依赖它们）。
    从 terminals 沿 deps 正向展开 = terminals 依赖的一切。"""
    seen, stack = set(), list(terminals)
    while stack:
        cur = stack.pop()
        for d in graph.get(cur, ()):
            if d not in seen:
                seen.add(d)
                stack.append(d)
    return seen


# ── CLI ──────────────────────────────────────────────────────────────
def _check_file(path: Path):
    try:
        src = path.read_text(encoding="utf-8")
        res = analyze_source(src, str(path))
    except SyntaxError as e:
        return {"file": str(path), "error": str(e)}
    except (OSError, UnicodeDecodeError) as e:
        return {"file": str(path), "error": f"{type(e).__name__}: {e}"}
    rules = [f["rule"] for f in res["findings"]]
    return {"file": str(path),
            "strategy_like": res["strategy_like"],
            "findings": res["findings"],
            "caught": bool(rules), "rules": rules}


def cmd_check(args):
    p = Path(args.path)
    if not p.exists():
        print(json.dumps({"tool": "lint", "version": VERSION,
                          "command": "check",
                          "error": f"path not found: {p}"}))
        return 2
    if p.is_file():
        if p.suffix != ".py":
            print(json.dumps({"tool": "lint", "version": VERSION,
                              "command": "check",
                              "error": f"not a .py file: {p}"}))
            return 2
        r = _check_file(p)
        if "error" in r:
            print(json.dumps({"tool": "lint", "version": VERSION,
                              "command": "check", "error": r["error"],
                              "file": r["file"]}))
            return 2
        out = dict(r)
        out["lint_version"] = VERSION
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    files = sorted(p.rglob("*.py"))
    results, errors = [], []
    for f in files:
        r = _check_file(f)
        (errors if "error" in r else results).append(r)
    if errors and not results:
        print(json.dumps({"tool": "lint", "version": VERSION,
                          "command": "check",
                          "error": f"{len(errors)} file(s) failed to "
                                   f"parse",
                          "files": errors}))
        return 2
    out = {"tool": "lint", "version": VERSION, "command": "check",
           "files": results + errors}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_gate(args):
    corpus = Path(args.corpus)
    exp_path = corpus / "expected_results.json"
    if not exp_path.exists():
        print(json.dumps({"tool": "lint", "version": VERSION,
                          "command": "gate",
                          "error": f"expected_results.json not found: "
                                   f"{exp_path}"}))
        return 2
    try:
        return _run_gate(corpus, exp_path)
    except Exception as e:  # gate mode honours the no-crash contract too.
        # A corpus that cannot be graded is an input error, not a verdict, so
        # this exits 2 and emits the same envelope shape as the not-found
        # branch above: an agent parses one contract either way. Before this
        # guard, a corrupt expected_results.json escaped as a bare traceback
        # with an empty stdout, which is exactly the failure an agent cannot
        # classify. The exception type is carried in the message so a genuine
        # internal bug stays diagnosable instead of being read as bad input.
        print(json.dumps({"tool": "lint", "version": VERSION,
                          "command": "gate",
                          "error": f"corpus could not be graded: "
                                   f"{type(e).__name__}: {e}"}))
        return 2


def _run_gate(corpus, exp_path):
    expected = json.loads(exp_path.read_text(encoding="utf-8"))
    cases, ok = [], 0
    for s in expected["samples"]:
        if s.get("module") != "lint":
            continue
        path = corpus / s["path"]
        r = _check_file(path)
        exp = s["expected"]
        tier_ok = True
        if exp.get("caught"):
            want = exp["rules"]
            got = r.get("rules", [])
            tier_ok = all(
                f["tier"] == exp.get("tier", "verified")
                for f in r.get("findings", []))
            passed = (r.get("caught") is True
                      and sorted(got) == sorted(want) and tier_ok)
        else:
            passed = r.get("caught") is False and r.get("rules") == []
        ok += 1 if passed else 0
        cases.append({"id": s["id"], "file": s["path"],
                      "expected": exp, "got": {
                          "caught": r.get("caught", False),
                          "rules": r.get("rules", []),
                          "tiers": [f["tier"] for f in
                                    r.get("findings", [])]},
                      "pass": passed})
    total = len(cases)
    passed_all = ok == total and total > 0
    print(json.dumps({
        "tool": "lint", "version": VERSION, "command": "gate",
        "pass": passed_all,
        "summary": {"pass": ok, "fail": total - ok, "total": total},
        "cases": cases}, indent=2, ensure_ascii=False))
    return 0 if passed_all else 1


# ── selftest ─────────────────────────────────────────────────────────
SELFTEST_CASES = [
    ("direct center=True fires 103",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["t"] = df["close"].rolling(21, center=True).mean()\n'
     '    df["s"] = (df["close"] > df["t"]).astype(int)\n'
     '    df["p"] = df["s"].shift(1).fillna(0)\n'
     '    df["r"] = df["close"].pct_change()\n'
     '    df["pnl"] = df["p"] * df["r"]\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.103"]}),
    ("kwargs passthrough center=True fires 103",
     'import pandas as pd\ndef smooth(s, **kw):\n'
     '    return s.rolling(**kw).mean()\n'
     'def run_backtest(df):\n'
     '    df["t"] = smooth(df["close"], window=20, center=True)\n'
     '    df["s"] = (df["close"] > df["t"]).astype(int)\n'
     '    df["p"] = df["s"].shift(1).fillna(0)\n'
     '    df["pnl"] = df["p"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.103"]}),
    ("rolling without center is clean",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["ma"] = df["close"].rolling(20).mean()\n'
     '    df["s"] = (df["close"] > df["ma"]).astype(int)\n'
     '    df["p"] = df["s"].shift(1).fillna(0)\n'
     '    df["pnl"] = df["p"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": []}),
    ("shift(-5) fires 104",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["fwd"] = df["close"].shift(-5)\n'
     '    df["s"] = (df["fwd"] > df["close"]).astype(int)\n'
     '    df["p"] = df["s"].shift(1).fillna(0)\n'
     '    df["pnl"] = df["p"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.104"]}),
    ("iloc[-1] in signal chain fires 104",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["n"] = df["close"] / df["close"].iloc[-1]\n'
     '    df["s"] = (df["n"] > 0.9).astype(int)\n'
     '    df["p"] = df["s"].shift(1).fillna(0)\n'
     '    df["pnl"] = df["p"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.104"]}),
    ("iloc[-1] in return-only is clean (reporting use)",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["ma"] = df["close"].rolling(20).mean()\n'
     '    df["s"] = (df["close"] > df["ma"]).astype(int)\n'
     '    df["p"] = df["s"].shift(1).fillna(0)\n'
     '    df["pnl"] = df["p"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    final = df["pnl"].iloc[-1]\n'
     '    return df, final\n',
     {"expect": []}),
    ("tail-slice std in signal chain fires 104",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    tv = df["close"].pct_change().iloc[-250:].std()\n'
     '    df["s"] = ((df["close"] / df["close"].iloc[0]) / tv > 1).astype(int)\n'
     '    df["p"] = df["s"].shift(1).fillna(0)\n'
     '    df["pnl"] = df["p"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.104"]}),
    ("unshifted position x close ret fires 101",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["ma"] = df["close"].rolling(20).mean()\n'
     '    df["signal"] = (df["close"] > df["ma"]).astype(int)\n'
     '    df["position"] = df["signal"]\n'
     '    df["ret"] = df["close"].pct_change()\n'
     '    df["pnl"] = df["position"] * df["ret"]\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.101"]}),
    ("unshifted position x open ret fires 102",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["ma"] = df["close"].rolling(20).mean()\n'
     '    df["position"] = (df["close"] > df["ma"]).astype(int)\n'
     '    df["pnl"] = df["position"] * df["open"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.102"], "evidence_has": "close"}),
    ("shifted position is clean (T+1 ok)",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    lookback = 20\n'
     '    roc = df["close"] / df["close"].shift(lookback) - 1\n'
     '    df["signal"] = (roc > 0).astype(int)\n'
     '    df["position"] = df["signal"].shift(1).fillna(0)\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    assert df["position"].isin([0, 1]).all()\n'
     '    return df\n',
     {"expect": []}),
    ("compare with both sides shifted is clean (inline T+1 lag)",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    ma = df["close"].rolling(20).mean()\n'
     '    df["position"] = (df["close"].shift(1) > ma.shift(1)).astype(int)\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": []}),
    ("both compare operands are price shifts is clean (inline T+1 lag)",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["position"] = (df["close"].shift(1) > df["close"].shift(20)).astype(int)\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": []}),
    ("lag on helper return is clean (T+1 via helper)",
     'import pandas as pd\ndef lagged(close):\n'
     '    sig = (close > close.rolling(20).mean()).astype(int)\n'
     '    return sig.shift(1)\n'
     'def run_backtest(df):\n'
     '    df["position"] = lagged(df["close"])\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": []}),
    ("lag inside np.where is clean (T+1 via where)",
     'import numpy as np\nimport pandas as pd\ndef run_backtest(df):\n'
     '    ma = df["close"].rolling(20).mean()\n'
     '    df["signal"] = (df["close"] > ma).astype(int)\n'
     '    df["position"] = np.where(df["signal"].shift(1).fillna(0) > 0, 1, 0)\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": []}),
    ("shift at pnl multiply is clean (locks current behavior)",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    ma = df["close"].rolling(20).mean()\n'
     '    df["signal"] = (df["close"] > ma).astype(int)\n'
     '    df["pnl"] = df["signal"].shift(1) * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": []}),
    ("shifted upper-band variable is clean (lag saved in variable)",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    upper = df["high"].rolling(20).max().shift(1)\n'
     '    df["position"] = (df["close"].shift(1) > upper).astype(int)\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": []}),
    ("fillna-wrapped unshifted position fires 101 (leak fix)",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    ma = df["close"].rolling(20).mean()\n'
     '    df["position"] = (df["close"] > ma).astype(int)\n'
     '    df["pnl"] = df["position"].fillna(0) * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.101"]}),
    ("inline-compare unshifted position fires 101 (kept)",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    ma = df["close"].rolling(20).mean()\n'
     '    df["position"] = (df["close"] > ma).astype(int)\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.101"]}),
    ("one shifted side is not enough: unshifted ma fires 101 (true same-bar)",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    ma = df["close"].rolling(20).mean()\n'
     '    df["position"] = (df["close"].shift(1) > ma).astype(int)\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.101"]}),
    ("open-only position x open ret fires 102 without close claim",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["position"] = (df["open"] > df["open"].shift(1)).astype(int)\n'
     '    df["pnl"] = df["position"] * df["open"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.102"], "no_evidence": "close"}),
    ("helper np.where unshifted x close ret fires 101 (alias cols)",
     'import numpy as np\nimport pandas as pd\n'
     'def entry(px, ref):\n'
     '    return np.where(px > ref, 1, 0)\n'
     'def run_backtest(df):\n'
     '    out = df.copy()\n'
     '    out["ref"] = out["close"].rolling(10).mean()\n'
     '    out["pos"] = entry(out["close"], out["ref"])\n'
     '    out["bar_ret"] = out["close"].pct_change()\n'
     '    out["strat_ret"] = out["pos"] * out["bar_ret"]\n'
     '    assert out["strat_ret"].notna().all()\n'
     '    return out\n',
     {"expect": ["lint.101"]}),
    ("loop same-bar fires 101",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    positions = []\n'
     '    for i in range(1, len(df)):\n'
     '        positions.append(1 if df["close"].iloc[i] > df["high"].iloc[i-1] else 0)\n'
     '    df = df.copy()\n'
     '    df["position"] = [0] + positions\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": ["lint.101"]}),
    ("loop lagged-only decision is clean",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    positions = []\n'
     '    for i in range(1, len(df)):\n'
     '        positions.append(1 if df["close"].iloc[i-1] > df["high"].iloc[i-1] else 0)\n'
     '    df = df.copy()\n'
     '    df["position"] = [0] + positions\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    return df\n',
     {"expect": []}),
    ("zero asserts fires 105",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["ma"] = df["close"].rolling(20).mean()\n'
     '    df["signal"] = (df["close"] > df["ma"]).astype(int)\n'
     '    df["position"] = df["signal"].shift(1).fillna(0)\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    return df\n',
     {"expect": ["lint.105"]}),
    ("vacuous asserts fire 105",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["ma"] = df["close"].rolling(20).mean()\n'
     '    df["signal"] = (df["close"] > df["ma"]).astype(int)\n'
     '    df["position"] = df["signal"].shift(1).fillna(0)\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert True\n'
     '    assert df is not None\n'
     '    return df\n',
     {"expect": ["lint.105"]}),
    ("meaningful asserts suppress 105",
     'import pandas as pd\ndef run_backtest(df):\n'
     '    df["ma"] = df["close"].rolling(20).mean()\n'
     '    df["signal"] = (df["close"] > df["ma"]).astype(int)\n'
     '    df["position"] = df["signal"].shift(1).fillna(0)\n'
     '    df["pnl"] = df["position"] * df["close"].pct_change()\n'
     '    assert df["pnl"].notna().all()\n'
     '    assert df["position"].isin([0, 1]).all()\n'
     '    return df\n',
     {"expect": []}),
    ("non-strategy file is cannot_determine (no findings, no 105)",
     'def add(a, b):\n'
     '    return a + b\n',
     {"expect": [], "strategy_like": False}),
]


def cmd_selftest(args):
    failures, n = [], 0
    for name, src, spec in SELFTEST_CASES:
        n += 1
        try:
            res = analyze_source(src)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{name}: raised {type(e).__name__}: {e}")
            continue
        got = [f["rule"] for f in res["findings"]]
        want = spec["expect"]
        ok = sorted(got) == sorted(want)
        if "strategy_like" in spec:
            ok = ok and res["strategy_like"] == spec["strategy_like"]
        if not ok:
            failures.append(f"{name}: expected {want}, got {got} "
                            f"(strategy_like={res['strategy_like']})")
        # evidence 内容断言（m-1：evidence 不得陈述代码未确立的事实）
        evs = " | ".join(f["evidence"] for f in res["findings"])
        if spec.get("no_evidence") and spec["no_evidence"] in evs:
            failures.append(f"{name}: evidence must not mention "
                            f"'{spec['no_evidence']}': {evs[:200]!r}")
        if spec.get("evidence_has") and spec["evidence_has"] not in evs:
            failures.append(f"{name}: evidence must mention "
                            f"'{spec['evidence_has']}': {evs[:200]!r}")
    # 105 不应在非策略文件触发（无 df 形态 → cannot_determine）
    # CLI 反控：语法错误 → exit 2 error JSON
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".py",
                                     delete=False) as fh:
        fh.write("def broken(:\n    pass\n")
        bad = fh.name
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "check", bad],
        capture_output=True, text=True)
    n += 1
    if r.returncode != 2 or "error" not in r.stdout:
        failures.append(
            f"CLI syntax-error probe: exit {r.returncode}, "
            f"stdout={r.stdout[:120]!r}")
    Path(bad).unlink(missing_ok=True)
    # CLI 反控：缺文件 → exit 2
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "check",
         "/nonexistent/lint_probe.py"],
        capture_output=True, text=True)
    n += 1
    if r.returncode != 2 or "error" not in r.stdout:
        failures.append(
            f"CLI missing-file probe: exit {r.returncode}, "
            f"stdout={r.stdout[:120]!r}")
    # corpus gate 正控
    corpus = Path(__file__).resolve().parent.parent / "tests" / "corpus"
    if corpus.exists():
        r = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "gate",
             "--corpus", str(corpus)],
            capture_output=True, text=True)
        n += 1
        try:
            g = json.loads(r.stdout)
        except json.JSONDecodeError:
            g = {}
        if r.returncode != 0 or not g.get("pass") \
                or g.get("summary", {}).get("total") != 18:
            failures.append(
                f"corpus gate: exit {r.returncode}, "
                f"summary={g.get('summary')}")
    else:
        n += 1
        failures.append("corpus gate: corpus dir not found")
    # CLI 反控：读不动的语料 → exit 2 + JSON 错误信封，且不得抛 traceback。
    # 没有这条，上面那个 except 分支就是"写了但没测"，退回 0.1.2 之前的
    # 逃逸行为也不会有任何断言变红。
    import shutil
    tmpd = Path(tempfile.mkdtemp(prefix="lint-corrupt-"))
    (tmpd / "expected_results.json").write_text("{", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "gate",
         "--corpus", str(tmpd)],
        capture_output=True, text=True)
    n += 1
    try:
        env = json.loads(r.stdout) if r.stdout.strip() else {}
    except json.JSONDecodeError:
        env = {}
    if (r.returncode != 2 or "error" not in env
            or "Traceback" in r.stderr):
        failures.append(
            f"corrupt-corpus probe: exit {r.returncode}, "
            f"stdout={r.stdout[:120]!r}, "
            f"traceback={'Traceback' in r.stderr}")
    shutil.rmtree(tmpd, ignore_errors=True)
    ok = not failures
    print(json.dumps({"tool": "lint", "version": VERSION,
                      "command": "selftest", "assertions": n,
                      "failures": failures, "ok": ok}))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lint.py")
    sub = ap.add_subparsers(dest="command", required=True)
    p_chk = sub.add_parser("check")
    p_chk.add_argument("path")
    p_gate = sub.add_parser("gate")
    p_gate.add_argument("--corpus", required=True)
    sub.add_parser("selftest")
    args = ap.parse_args(argv)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "gate":
        return cmd_gate(args)
    return cmd_selftest(args)


if __name__ == "__main__":
    sys.exit(main())
