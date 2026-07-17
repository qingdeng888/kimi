from app.kimi.model_catalog import parse_model_catalog


LATEST_MODELS_RESPONSE = {
    "availableModels": [
        {
            "scenario": "SCENARIO_OK_COMPUTER",
            "displayName": "K3 · Max",
            "description": "擅长对话与 Agent 任务，全能旗舰",
            "kimiPlusId": "ok-computer",
            "agentMode": "TYPE_NORMAL",
            "key": "k3",
            "contextLengthOptions": [
                {"contextLength": "CONTEXT_LENGTH_L", "displayName": "标准", "available": True},
                {
                    "contextLength": "CONTEXT_LENGTH_XL",
                    "displayName": "超长",
                    "minMembershipLevel": "LEVEL_ADVANCED",
                },
            ],
            "defaultContextLength": "CONTEXT_LENGTH_L",
        },
        {
            "scenario": "SCENARIO_OK_COMPUTER",
            "displayName": "K3 集群 · Max",
            "kimiPlusId": "ok-computer",
            "agentMode": "TYPE_ULTRA",
            "key": "k3-agent-ultra",
            "contextLengthOptions": [
                {"contextLength": "CONTEXT_LENGTH_L", "displayName": "标准", "available": True},
                {
                    "contextLength": "CONTEXT_LENGTH_XL",
                    "displayName": "超长",
                    "minMembershipLevel": "LEVEL_ADVANCED",
                },
            ],
            "defaultContextLength": "CONTEXT_LENGTH_L",
        },
        {
            "scenario": "SCENARIO_K2D5",
            "displayName": "K2.6 · Fast",
            "key": "k2d6",
            "reasoningEffortOptions": [
                {"effort": "REASONING_EFFORT_NONE", "displayName": "标准"},
                {"effort": "REASONING_EFFORT_LOW", "displayName": "进阶"},
            ],
            "defaultReasoningEffort": "REASONING_EFFORT_NONE",
        },
    ],
    "defaultScenario": {"scenario": "SCENARIO_OK_COMPUTER"},
}


def test_parse_latest_model_catalog_expands_context_and_reasoning_variants():
    catalog = parse_model_catalog(LATEST_MODELS_RESPONSE)

    assert [model.id for model in catalog.models] == [
        "kimi-k3",
        "kimi-k2.6",
        "kimi-k2.6-thinking",
        "kimi-k2.6-search",
        "kimi-k2.6-thinking-search",
    ]
    assert catalog.default_model_id == "kimi-k3"

    k3 = catalog.by_id("kimi-k3")
    assert k3.model_key == "k3"
    assert k3.context_length == "CONTEXT_LENGTH_L"
    assert k3.agent_mode == "TYPE_NORMAL"
    assert k3.upstream_thinking is True
    assert k3.enable_plugin is True

    assert catalog.by_id("kimi-k3-long") is None
    assert catalog.by_id("kimi-k3-agent-swarm") is None
    assert catalog.by_id("kimi-k3-agent-swarm-long") is None

    fast = catalog.by_id("kimi-k2.6")
    assert fast.reasoning_effort == "REASONING_EFFORT_NONE"
    assert fast.thinking is False

    thinking = catalog.by_id("kimi-k2.6-thinking")
    assert thinking.reasoning_effort == "REASONING_EFFORT_LOW"
    assert thinking.thinking is True

    assert catalog.by_id("kimi-k2.6-search").base_model_id == "kimi-k2.6"
    assert catalog.by_id("kimi-k2.6-thinking-search").base_model_id == "kimi-k2.6-thinking"


def test_available_long_context_is_exposed_for_entitled_account():
    response = {
        "availableModels": [{
            "scenario": "SCENARIO_OK_COMPUTER",
            "displayName": "K3 · Max",
            "kimiPlusId": "ok-computer",
            "agentMode": "TYPE_NORMAL",
            "key": "k3",
            "contextLengthOptions": [
                {"contextLength": "CONTEXT_LENGTH_L", "displayName": "标准", "available": True},
                {
                    "contextLength": "CONTEXT_LENGTH_XL",
                    "displayName": "超长",
                    "available": True,
                    "minMembershipLevel": "LEVEL_ADVANCED",
                },
            ],
            "defaultContextLength": "CONTEXT_LENGTH_L",
        }],
        "defaultScenario": {"scenario": "SCENARIO_OK_COMPUTER"},
    }

    catalog = parse_model_catalog(response)

    assert catalog.by_id("kimi-k3-long").context_length == "CONTEXT_LENGTH_XL"


def test_explicitly_available_cluster_is_exposed_for_entitled_account():
    response = {
        "availableModels": [{
            "scenario": "SCENARIO_OK_COMPUTER",
            "displayName": "K3 集群 · Max",
            "kimiPlusId": "ok-computer",
            "agentMode": "TYPE_ULTRA",
            "key": "k3-agent-ultra",
            "available": True,
            "contextLengthOptions": [
                {"contextLength": "CONTEXT_LENGTH_L", "displayName": "标准", "available": True},
            ],
            "defaultContextLength": "CONTEXT_LENGTH_L",
        }],
        "defaultScenario": {"scenario": "SCENARIO_OK_COMPUTER"},
    }

    catalog = parse_model_catalog(response)

    assert catalog.by_id("kimi-k3-agent-swarm").agent_mode == "TYPE_ULTRA"
