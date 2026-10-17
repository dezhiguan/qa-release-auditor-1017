import pytest
from unittest.mock import AsyncMock, MagicMock
import json
from typing import Dict, Any

# Import the execute function
from role import execute

@pytest.mark.asyncio
async def test_execute_normal_flow():
    # Mock context
    ctx = MagicMock()
    
    # Mock manifest with two delegates
    ctx.manifest.spec.delegates = ["qa-devops-investigator-1017", "qa-policy-advisor-1017"]
    
    # Mock prompt
    mock_prompt = MagicMock()
    mock_prompt.compile = MagicMock(return_value="Compiled prompt with evidence")
    ctx.prompt = AsyncMock(return_value=mock_prompt)
    
    # Mock LLM
    ctx.llm.chat = AsyncMock(return_value='{"decision": "PASS"}')
    
    # Mock tools
    ctx.tools.call = AsyncMock(side_effect=[
        [{"id": "DF-0007", "status": "completed"}],  # devflow.job.read
        {"log": "build passed", "logsUnavailable": False},  # ci.log.fetch
        {"diff": "diff --git a/file.py b/file.py", "number": 1}  # git.pr.diff
    ])
    
    # Mock delegate responses — return full encapsulated dicts
    ctx.delegate = AsyncMock(side_effect=[
        {"result": "DevOps review: CI log confirms build success"},
        {"result": "Policy review: PR diff contains no PII"}
    ])
    
    # Input data
    data = {
        "text": "请对仓库 qa-release-checker-1017 的 CI runId 39010072606、PR #1、任务 DF-0007 执行核对主分支构建与差异，给出可追溯结论。严格按工具返回内容判断；这是证据核验，不代表自动合并或发布。"
    }
    
    # Execute
    result = await execute(data, ctx)
    
    # Assert structure
    assert isinstance(result, dict)
    assert "decision" in result
    assert result["decision"] == "PASS"
    assert "evidence" in result
    assert "sub_agents" in result["evidence"]
    assert len(result["evidence"]["sub_agents"]) == 2
    assert "steps" in result
    assert len(result["steps"]) == 5
    assert "input" in result
    assert result["input"]["repo"] == "qa-release-checker-1017"
    assert result["input"]["runId"] == "39010072606"
    assert result["input"]["pr_number"] == "1"
    assert result["input"]["jobId"] == "DF-0007"


@pytest.mark.asyncio
async def test_execute_missing_repo():
    ctx = MagicMock()
    ctx.manifest.spec.delegates = ["qa-devops-investigator-1017", "qa-policy-advisor-1017"]
    
    ctx.prompt = AsyncMock()
    ctx.llm.chat = AsyncMock()
    ctx.tools.call = AsyncMock()
    ctx.delegate = AsyncMock()
    
    data = {
        "text": "CI runId 39010072606、PR #1、任务 DF-0007 请核验。"
    }
    
    result = await execute(data, ctx)
    
    assert result["decision"] == "BLOCKED"
    assert "repo" in result["reason"]


@pytest.mark.asyncio
async def test_execute_child_blocked_remains_blocked_when_model_says_pass():
    ctx = MagicMock()
    ctx.manifest.spec.delegates = ["qa-devops-investigator-1017", "qa-policy-advisor-1017"]
    
    mock_prompt = MagicMock()
    mock_prompt.compile = MagicMock(return_value="Compiled prompt")
    ctx.prompt = AsyncMock(return_value=mock_prompt)
    
    ctx.llm.chat = AsyncMock(return_value='{"decision": "PASS", "reason": "All looks fine"}')
    
    # Simulate devflow.job.read succeeds
    ctx.tools.call = AsyncMock(side_effect=[
        [{"id": "DF-0007", "status": "completed"}],
        {"log": "build passed", "logsUnavailable": False},
        {"diff": "...", "number": 1}
    ])
    
    # First delegate returns BLOCKED result (as full dict with decision)
    ctx.delegate = AsyncMock(side_effect=[
        {"result": {"decision": "BLOCKED", "reason": "missing artifact"}},
        {"result": "Policy review OK"}
    ])
    
    data = {
        "text": "请对仓库 qa-release-checker-1017 的 CI runId 39010072606、PR #1、任务 DF-0007 执行核对主分支构建与差异。"
    }
    
    result = await execute(data, ctx)
    
    assert result["decision"] == "BLOCKED"
    assert "Delegate qa-devops-investigator-1017 returned BLOCKED decision" in result["reason"]


@pytest.mark.asyncio
async def test_execute_ci_log_empty_blocked():
    ctx = MagicMock()
    ctx.manifest.spec.delegates = ["qa-devops-investigator-1017", "qa-policy-advisor-1017"]
    
    mock_prompt = MagicMock()
    mock_prompt.compile = MagicMock(return_value="Compiled prompt")
    ctx.prompt = AsyncMock(return_value=mock_prompt)
    
    ctx.llm.chat = AsyncMock(return_value='{"decision": "PASS"}')
    
    # ci.log.fetch returns empty log
    ctx.tools.call = AsyncMock(side_effect=[
        [{"id": "DF-0007", "status": "completed"}],
        {"log": "", "logsUnavailable": False},
        {"diff": "...", "number": 1}
    ])
    
    ctx.delegate = AsyncMock(side_effect=[
        {"result": "DevOps review OK"},
        {"result": "Policy review OK"}
    ])
    
    data = {
        "text": "请对仓库 qa-release-checker-1017 的 CI runId 39010072606、PR #1、任务 DF-0007 执行核对主分支构建与差异。"
    }
    
    result = await execute(data, ctx)
    
    assert result["decision"] == "BLOCKED"
    assert "ci.log.fetch 'log' is empty or whitespace" in result["reason"]


@pytest.mark.asyncio
async def test_execute_pr_diff_empty_blocked():
    ctx = MagicMock()
    ctx.manifest.spec.delegates = ["qa-devops-investigator-1017", "qa-policy-advisor-1017"]
    
    mock_prompt = MagicMock()
    mock_prompt.compile = MagicMock(return_value="Compiled prompt")
    ctx.prompt = AsyncMock(return_value=mock_prompt)
    
    ctx.llm.chat = AsyncMock(return_value='{"decision": "PASS"}')
    
    # git.pr.diff returns empty diff
    ctx.tools.call = AsyncMock(side_effect=[
        [{"id": "DF-0007", "status": "completed"}],
        {"log": "build passed", "logsUnavailable": False},
        {"diff": "", "number": 1}
    ])
    
    ctx.delegate = AsyncMock(side_effect=[
        {"result": "DevOps review OK"},
        {"result": "Policy review OK"}
    ])
    
    data = {
        "text": "请对仓库 qa-release-checker-1017 的 CI runId 39010072606、PR #1、任务 DF-0007 执行核对主分支构建与差异。"
    }
    
    result = await execute(data, ctx)
    
    assert result["decision"] == "BLOCKED"
    assert "git.pr.diff 'diff' is empty or whitespace" in result["reason"]