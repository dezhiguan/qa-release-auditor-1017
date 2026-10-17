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
    
    # Mock delegate responses
    ctx.delegate = AsyncMock(side_effect=[
        {"result": "DevOps review: CI log confirms build success", "agent": "qa-devops-investigator-1017"},
        {"result": "Policy review: PR diff contains no PII", "agent": "qa-policy-advisor-1017"}
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
async def test_execute_tool_failure():
    ctx = MagicMock()
    ctx.manifest.spec.delegates = ["qa-devops-investigator-1017", "qa-policy-advisor-1017"]
    
    ctx.prompt = AsyncMock()
    ctx.llm.chat = AsyncMock()
    
    # Simulate ci.log.fetch raises exception
    ctx.tools.call = AsyncMock(side_effect=[
        [{"id": "DF-0007", "status": "completed"}],
        Exception("network timeout"),
        {"diff": "...", "number": 1}
    ])
    
    ctx.delegate = AsyncMock()
    
    data = {
        "text": "请对仓库 qa-release-checker-1017 的 CI runId 39010072606、PR #1、任务 DF-0007 执行核对主分支构建与差异。"
    }
    
    result = await execute(data, ctx)
    
    assert result["decision"] == "BLOCKED"
    assert "ci.log.fetch call failed" in result["reason"]