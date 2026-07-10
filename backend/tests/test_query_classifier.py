"""query_classifier 纯逻辑单测 —— 关键词路由分桶。"""
from funcation.query_classifier import classify_query, QUERY_TYPE_WEIGHTS


def test_profile_keywords():
    assert classify_query("你还记得我是谁吗") == "profile"
    assert classify_query("我的名字叫什么") == "profile"
    assert classify_query("你记得我的工作吗") == "profile"


def test_relationship_keywords():
    assert classify_query("你是不是喜欢我") == "relationship"
    assert classify_query("我们的关系怎么样") == "relationship"
    assert classify_query("你会在意我吗") == "relationship"


def test_story_keywords():
    assert classify_query("之前那次发生了什么") == "story"
    assert classify_query("你记不记得那个剧情") == "story"


def test_event_keywords():
    assert classify_query("最近有什么活动") == "event"
    assert classify_query("运动会的事") == "event"
    assert classify_query("世界发生了什么") == "event"


def test_general_fallback():
    assert classify_query("今天吃什么") == "general"
    assert classify_query("你好") == "general"
    assert classify_query("") == "general"


def test_case_insensitive():
    # 分类器内部做了 text.lower()，但中文不受影响；这里验证不会因大小写炸
    assert classify_query("Hello") == "general"


def test_weights_table_structure():
    """QUERY_TYPE_WEIGHTS 每个桶都覆盖全部集合，权重为正数。"""
    collections = {"profile", "relationship", "long_memory", "story", "events", "chat_summary"}
    for bucket, weights in QUERY_TYPE_WEIGHTS.items():
        assert set(weights.keys()) == collections, f"桶 {bucket} 集合不完整"
        for v in weights.values():
            assert isinstance(v, (int, float)) and v > 0
