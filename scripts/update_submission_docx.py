#!/usr/bin/env python3
"""Create the current StratPilot competition introduction from the visual template."""

from pathlib import Path

from docx import Document


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifact" / "企业经营决策Agent_作品简介.docx"
TARGET = ROOT / "artifact" / "StratPilot_作品简介.docx"

INTRODUCTION = (
    "StratPilot 是一套面向企业经营沙盘的单企业人机协同决策系统。比赛中，订单、采购、生产能力、库存、研发、融资和现金预算彼此制约，而参赛者往往只能观察本企业状态、当前公开订单及规则允许的信息，容易出现订单承诺超过产能、资金链断裂和决策难以复盘等问题。"
    "系统将比赛规则、本企业私有状态和当前公开信息组织为统一观察，由资金、资格、产能、供应履约、订单组合和风险模块协同形成稳健、平衡或增长方案，并给出可读理由、参考公式和禁忌操作。用户可继续向 Agent 提问、修改动作后再提交；订单分配、财务结算、违约、破产和报表由独立模拟环境统一判定，Agent 的预期不能直接改变结果。系统同时记录季度反馈、人机方案差异和终局轨迹，用于赛后复盘与 VPD 验收。"
    "项目创新在于把部分可观测决策、确定性财务状态机、多专业 Agent 协作、反事实接口和可审计解释连成一个闭环，使系统既能辅助真实参赛者，也能在本地生成多种对手和订单场景进行鲁棒性测试。"
)


def main() -> None:
    document = Document(SOURCE)
    document.paragraphs[0].text = "StratPilot"
    document.paragraphs[1].text = "Enterprise Decision Agent · 企业经营沙盘决策智能体"
    document.paragraphs[3].text = INTRODUCTION
    document.core_properties.title = "StratPilot 作品简介"
    document.core_properties.subject = "Enterprise Decision Agent"
    document.save(TARGET)
    print(TARGET)


if __name__ == "__main__":
    main()
