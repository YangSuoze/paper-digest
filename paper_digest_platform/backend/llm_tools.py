import logging
import time
import asyncio
import json
import base64
import mimetypes
import os
from typing import Optional, Dict, List, Union, Type, AsyncGenerator
import numpy as np
from openai import (
    OpenAI,
    AsyncOpenAI,
    APITimeoutError,
    APIConnectionError,
    RateLimitError,
    InternalServerError,
)
from pydantic import BaseModel
from app.core.config import get_settings

# --- 类型定义 ---
MessageList = List[
    Dict[str, any]
]  # ### MODIFIED ###: content can be a list of dicts for vision


def pydantic_compat(cls):
    """完整的 Pydantic v1/v2 兼容性装饰器"""
    try:
        import pydantic

        # 检测 Pydantic 版本
        version = getattr(pydantic, "__version__", "1.0.0")
        major_version = int(version.split(".")[0])

        if major_version < 2:
            # Pydantic v1 兼容性补丁

            # 1. model_json_schema 方法 (v2: model_json_schema, v1: schema)
            if not hasattr(cls, "model_json_schema"):
                if hasattr(cls, "schema"):
                    cls.model_json_schema = classmethod(lambda c: c.schema())
                else:

                    def basic_schema(c):
                        return {"type": "object", "properties": {}, "required": []}

                    cls.model_json_schema = classmethod(basic_schema)

            # 2. model_validate_json 方法 (v2: model_validate_json, v1: parse_raw)
            if not hasattr(cls, "model_validate_json"):
                if hasattr(cls, "parse_raw"):
                    cls.model_validate_json = classmethod(
                        lambda c, json_str: c.parse_raw(json_str)
                    )
                else:

                    def parse_json_fallback(c, json_str):
                        import json

                        data = json.loads(json_str)
                        return c(**data)

                    cls.model_validate_json = classmethod(parse_json_fallback)

            # 3. model_validate 方法 (v2: model_validate, v1: parse_obj)
            if not hasattr(cls, "model_validate"):
                if hasattr(cls, "parse_obj"):
                    cls.model_validate = classmethod(lambda c, obj: c.parse_obj(obj))
                else:
                    cls.model_validate = classmethod(lambda c, obj: c(**obj))

            # 4. model_dump 方法 (v2: model_dump, v1: dict)
            if not hasattr(cls, "model_dump"):

                def model_dump_v1(self, **kwargs):
                    if hasattr(self, "dict"):
                        return self.dict(**kwargs)
                    else:
                        # 基础 fallback
                        return {k: getattr(self, k) for k in self.__fields__.keys()}

                cls.model_dump = model_dump_v1

            # 5. model_dump_json 方法 (v2: model_dump_json, v1: json)
            if not hasattr(cls, "model_dump_json"):

                def model_dump_json_v1(self, **kwargs):
                    if hasattr(self, "json"):
                        return self.json(**kwargs)
                    else:
                        import json

                        return json.dumps(self.model_dump(**kwargs), ensure_ascii=False)

                cls.model_dump_json = model_dump_json_v1

            # 6. model_copy 方法 (v2: model_copy, v1: copy)
            if not hasattr(cls, "model_copy"):

                def model_copy_v1(self, **kwargs):
                    if hasattr(self, "copy"):
                        return self.copy(**kwargs)
                    else:
                        # 基础 fallback
                        data = self.model_dump()
                        data.update(kwargs)
                        return self.__class__(**data)

                cls.model_copy = model_copy_v1

    except Exception as e:
        # 如果检测失败，添加安全的默认方法
        def safe_method_factory(method_name, fallback_value=None):
            def safe_method(*args, **kwargs):
                raise NotImplementedError(
                    f"{method_name} not available in this Pydantic version"
                )

            return safe_method

        if not hasattr(cls, "model_json_schema"):
            cls.model_json_schema = classmethod(
                lambda c: {"type": "object", "properties": {}, "required": []}
            )
        if not hasattr(cls, "model_validate_json"):
            cls.model_validate_json = classmethod(
                safe_method_factory("model_validate_json")
            )
        if not hasattr(cls, "model_validate"):
            cls.model_validate = classmethod(safe_method_factory("model_validate"))
        if not hasattr(cls, "model_dump"):
            cls.model_dump = safe_method_factory("model_dump")
        if not hasattr(cls, "model_dump_json"):
            cls.model_dump_json = safe_method_factory("model_dump_json")
        if not hasattr(cls, "model_copy"):
            cls.model_copy = safe_method_factory("model_copy")

    return cls


# Pydantic 兼容性工具函数
def validate_json_compat(model_class: Type[BaseModel], json_str: str):
    """兼容的 JSON 验证函数"""
    try:
        if hasattr(model_class, "model_validate_json"):
            return model_class.model_validate_json(json_str)
        elif hasattr(model_class, "parse_raw"):
            return model_class.parse_raw(json_str)
        else:
            import json

            data = json.loads(json_str)
            return model_class(**data)
    except Exception as e:
        raise ValueError(f"Failed to validate JSON with {model_class.__name__}: {e}")


def validate_dict_compat(model_class: Type[BaseModel], data: dict):
    """兼容的字典验证函数"""
    try:
        if hasattr(model_class, "model_validate"):
            return model_class.model_validate(data)
        elif hasattr(model_class, "parse_obj"):
            return model_class.parse_obj(data)
        else:
            return model_class(**data)
    except Exception as e:
        raise ValueError(f"Failed to validate dict with {model_class.__name__}: {e}")


def model_dump_compat(instance: BaseModel, **kwargs):
    """兼容的模型转字典函数"""
    try:
        if hasattr(instance, "model_dump"):
            return instance.model_dump(**kwargs)
        elif hasattr(instance, "dict"):
            return instance.dict(**kwargs)
        else:
            # 基础 fallback
            return {k: getattr(instance, k) for k in instance.__fields__.keys()}
    except Exception as e:
        raise ValueError(f"Failed to dump model {instance.__class__.__name__}: {e}")


def model_dump_json_compat(instance: BaseModel, **kwargs):
    """兼容的模型转JSON字符串函数"""
    try:
        if hasattr(instance, "model_dump_json"):
            return instance.model_dump_json(**kwargs)
        elif hasattr(instance, "json"):
            return instance.json(**kwargs)
        else:
            import json

            return json.dumps(model_dump_compat(instance, **kwargs), ensure_ascii=False)
    except Exception as e:
        raise ValueError(
            f"Failed to dump JSON for model {instance.__class__.__name__}: {e}"
        )


class LLMClient:
    """
    一个精简且高性能的大模型请求客户端，基于官方 openai 库重构。
    专为同步/异步查询和获取Embeddings设计，并针对FastAPI等异步框架进行了优化。
    现已支持 Qwen 和 vLLM 的 JSON Mode/Schema 功能，以及本地视觉模型。
    """

    def __init__(self):
        # ... (和之前版本完全一样，无需改动)
        # 配置日志
        self.logger = logging.getLogger("LLMClient")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

        # 缓存 OpenAI 客户端实例
        self._sync_client_cache: Dict[str, OpenAI] = {}
        self._async_client_cache: Dict[str, AsyncOpenAI] = {}
        self._embedding_client_cache: Dict[str, OpenAIEmbeddingsClient] = {}

        # 重试策略配置
        self.max_retries = 3
        self.retry_delay = 1  # 秒
        self.retryable_errors = (
            APITimeoutError,
            APIConnectionError,
            RateLimitError,
            InternalServerError,
        )

        # 专门用于 Qwen API 的 JSON Mode 支持的模型列表
        self.qwen_json_supported_models = {
            "qwen-max",
            "qwen-max-latest",
            "qwen-plus",
            "qwen-plus-latest",
            "qwen-flash",
            "qwen-flash-latest",
            "qwen-turbo",
            "qwen-turbo-latest",
            "qwen2.5",
            "qwen-vl-max",
            "qwen-vl-plus",
            "qwen3-max",
        }

    def _create_client_cache_key(self, api_base: str, api_key: str) -> str:
        """为 OpenAI 客户端创建缓存键"""
        return f"{api_base}_{hash(api_key)}"

    def _get_sync_client(self, api_base: str, api_key: str) -> OpenAI:
        """获取同步 OpenAI 客户端实例，使用缓存"""
        cache_key = self._create_client_cache_key(api_base, api_key)
        if cache_key not in self._sync_client_cache:
            self._sync_client_cache[cache_key] = OpenAI(
                api_key=api_key,
                base_url=api_base,
                timeout=120,
                max_retries=2,
            )
        return self._sync_client_cache[cache_key]

    def _get_async_client(self, api_base: str, api_key: str) -> AsyncOpenAI:
        """获取异步 OpenAI 客户端实例，使用缓存"""
        cache_key = self._create_client_cache_key(api_base, api_key)
        if cache_key not in self._async_client_cache:
            self._async_client_cache[cache_key] = AsyncOpenAI(
                api_key=api_key,
                base_url=api_base,
                timeout=120,
                max_retries=2,
            )
        return self._async_client_cache[cache_key]

    def _get_embedding_client(
        self, api_base: str, api_key: str
    ) -> "OpenAIEmbeddingsClient":
        """获取一个封装了同步和异步方法的Embedding客户端"""
        cache_key = self._create_client_cache_key(api_base, api_key)
        if cache_key not in self._embedding_client_cache:
            self._embedding_client_cache[cache_key] = OpenAIEmbeddingsClient(
                api_base=api_base, api_key=api_key
            )
        return self._embedding_client_cache[cache_key]

    ### NEW ###
    def _encode_image_to_base64_url(self, image_path: str) -> str:
        """将图片文件或URL转换为Base64 data URL"""
        if image_path.startswith(("http://", "https://")):
            # 如果已经是URL，直接返回
            return image_path

        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found at: {image_path}")

        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith("image"):
            raise ValueError(f"File is not a recognized image type: {image_path}")

        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")

        return f"data:{mime_type};base64,{encoded_string}"

    ### MODIFIED ###
    def _prepare_messages(
        self,
        query: Union[str, MessageList],
        system_message: str = None,
        image_url: Optional[str] = None,
    ) -> MessageList:
        """准备发送给模型的消息格式，现已支持视觉模型。"""
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})

        # 如果是视觉查询
        if image_url:
            if not isinstance(query, str):
                raise ValueError(
                    "When providing an image_url, the 'query' parameter must be a string (the text prompt)."
                )

            encoded_image_url = self._encode_image_to_base64_url(image_url)

            user_content = [
                # --- 这是修正的行 ---
                {"type": "text", "text": query},  # <-- 将 "content" 修改为 "text"
                # ---------------------
                {
                    "type": "image_url",
                    "image_url": {"url": encoded_image_url},
                },
            ]
            messages.append({"role": "user", "content": user_content})

        # 如果是普通文本查询
        else:
            if isinstance(query, list):
                # 如果已经是消息列表格式，直接使用（可以考虑与 system_message 合并）
                temp_messages = query
                if system_message and not any(
                    msg.get("role") == "system" for msg in temp_messages
                ):
                    messages.extend(temp_messages)
                else:
                    # 如果query里已经有system message，则用query里的，忽略外部的system_message
                    messages = temp_messages
            elif isinstance(query, str):
                messages.append({"role": "user", "content": query})

        return messages

    def _build_request_kwargs(
        self,
        deployment: str,
        model_name: str,
        messages: MessageList,
        enable_thinking: bool,
        json_mode: Union[bool, Type[BaseModel]],
    ) -> Dict:
        """构建传递给 OpenAI API 的参数字典"""
        kwargs = {}
        # 1. 处理 JSON 输出模式
        if json_mode:
            if deployment.startswith("local"):  # vLLM
                if isinstance(json_mode, type) and issubclass(json_mode, BaseModel):
                    kwargs["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": json_mode.__name__,
                            "description": json_mode.__doc__ or "No description",
                            "schema": json_mode.schema(),  # 使用 v1 的 schema() 方法
                        },
                    }
                    self.logger.info(
                        f"vLLM JSON Schema mode enabled for model {model_name} with schema {json_mode.__name__}."
                    )
                elif json_mode is True:
                    # vLLM 也兼容 OpenAI 的 json_object 格式
                    kwargs["response_format"] = {"type": "json_object"}
                    self.logger.info(
                        f"vLLM generic JSON Object mode enabled for model {model_name}."
                    )
            elif deployment == "ali":  # Qwen
                model_lower = model_name.lower()
                is_supported = any(
                    supported in model_lower
                    for supported in self.qwen_json_supported_models
                )
                if not is_supported:
                    raise ValueError(
                        f"Model {model_name} on 'ali' deployment does not support JSON Mode."
                    )
                # Qwen 要求 prompt 中包含 'json' 关键字
                all_content = ""
                for msg in messages:
                    # 兼容多模态消息
                    if isinstance(msg.get("content"), str):
                        all_content += msg["content"].lower()
                    elif isinstance(msg.get("content"), list):
                        for part in msg["content"]:
                            if part.get("type") == "text":
                                all_content += part.get("content", "").lower()
                if "json" not in all_content:
                    raise ValueError(
                        "For Qwen's JSON mode, 'messages' must contain the word 'json'."
                    )
                kwargs["response_format"] = {"type": "json_object"}
                self.logger.info(f"Qwen JSON Mode enabled for {model_name}.")
                if enable_thinking:
                    self.logger.warning(
                        "JSON Mode is enabled, automatically disabling thinking mode for Qwen."
                    )
                    enable_thinking = False
        # 2. 处理 Qwen 的思考模式 (仅在非 JSON 模式下)
        if (
            enable_thinking
            and not json_mode
            and "qwen" in model_name.lower()
            and deployment == "ali"
        ):
            kwargs["extra_body"] = {"enable_thinking": True}
            self.logger.info(f"Qwen thinking mode enabled for {model_name}.")
        return kwargs

    ### MODIFIED ###
    def query(
        self,
        query: Union[str, MessageList],
        model_name: str = "deepseek-v3",
        temperature: float = 1.0,
        deployment: str = "ali",
        system_message: str = None,
        enable_thinking: bool = False,
        json_mode: Union[bool, Type[BaseModel]] = False,
        image_url: Optional[str] = None,  # <-- 新增参数
    ) -> str:
        last_error = None
        for attempt in range(self.max_retries):
            try:
                api_config = self._get_api_config(deployment)
                client = self._get_sync_client(
                    api_config["api_base"], api_config["api_key"]
                )

                # 准备消息，传入 image_url
                messages = self._prepare_messages(query, system_message, image_url)

                request_kwargs = self._build_request_kwargs(
                    deployment, model_name, messages, enable_thinking, json_mode
                )

                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=temperature,
                    **request_kwargs,
                )
                return response.choices[0].message.content
            except self.retryable_errors as e:
                last_error = e
                wait_time = self.retry_delay * (2**attempt)
                self.logger.warning(
                    f"Attempt {attempt + 1}/{self.max_retries} failed. Retrying in {wait_time}s. Error: {e}"
                )
                time.sleep(wait_time)
            except Exception as e:
                self.logger.error(f"Non-retryable error in query: {e}")
                raise
        raise (
            last_error
            if last_error
            else Exception("Unknown error in query after max retries")
        )

    ### MODIFIED ###
    async def aquery(
        self,
        query: Union[str, MessageList],
        model_name: str = "deepseek-v3",
        temperature: float = 1.0,
        deployment: str = "ali",
        system_message: str = None,
        enable_thinking: bool = False,
        json_mode: Union[bool, Type[BaseModel]] = False,
        image_url: Optional[str] = None,  # <-- 新增参数
    ) -> str:
        last_error = None
        for attempt in range(self.max_retries):
            try:
                api_config = self._get_api_config(deployment)
                client = self._get_async_client(
                    api_config["api_base"], api_config["api_key"]
                )

                # 准备消息，传入 image_url
                messages = self._prepare_messages(query, system_message, image_url)

                request_kwargs = self._build_request_kwargs(
                    deployment, model_name, messages, enable_thinking, json_mode
                )

                response = await client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=temperature,
                    **request_kwargs,
                )
                return response.choices[0].message.content
            except self.retryable_errors as e:
                last_error = e
                wait_time = self.retry_delay * (2**attempt)
                self.logger.warning(
                    f"Async attempt {attempt + 1}/{self.max_retries} failed. Retrying in {wait_time}s. Error: {e}"
                )
                await asyncio.sleep(wait_time)
            except Exception as e:
                self.logger.error(f"Non-retryable error in aquery: {e}")
                raise
        raise (
            last_error
            if last_error
            else Exception("Unknown error in aquery after max retries")
        )

    def _preprocess_token(self, token: str, tmp_cache: dict):
        new_token = ""
        for item in token:
            if item == "[":
                # 入栈
                tmp_cache["before_seg"] = "["
            elif item == "]":
                # 出栈
                tmp_cache["before_seg"] += "]"
                if (
                    "本地数据库" in tmp_cache["before_seg"]
                    or "i" in tmp_cache["before_seg"]
                ):
                    new_token += ""
                else:
                    # 当前小程序不需要展示引用信息，所以注释掉这行
                    # new_token += tmp_cache["before_seg"]
                    new_token += ""
                tmp_cache["before_seg"] = ""
            else:
                # 检查栈不为空，入栈，为空则pass
                if len(tmp_cache["before_seg"]):
                    tmp_cache["before_seg"] += item
                else:
                    new_token += item
        return new_token

    async def aquery_stream(
        self,
        query: Union[str, MessageList],
        model_name: str = "deepseek-v3",
        temperature: float = 1.0,
        deployment: str = "ali",
        is_preprocess_token: bool = False,
        system_message: str = None,
        enable_thinking: bool = False,
        json_mode: Union[bool, Type[BaseModel]] = False,
        image_url: Optional[str] = None,  # <-- 新增参数
    ) -> AsyncGenerator[str, None]:
        last_error = None
        for attempt in range(self.max_retries):
            try:
                api_config = self._get_api_config(deployment)
                client = self._get_async_client(
                    api_config["api_base"], api_config["api_key"]
                )

                # 准备消息，传入 image_url
                messages = self._prepare_messages(query, system_message, image_url)

                request_kwargs = self._build_request_kwargs(
                    deployment, model_name, messages, enable_thinking, json_mode
                )

                response = await client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    stream=True,
                    temperature=temperature,
                    **request_kwargs,
                )
                tmp_cache = {
                    "reference_flag": "",
                    "before_toekn_text": "",
                    "before_seg": "",
                }
                reasoning_start_flag = True
                async for chunk in response:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, "reasoning_content"):
                            if reasoning_start_flag:
                                reasoning_start_flag = False
                                yield {"type": "reasoning", "token": "\n > "}
                            reasoning_token = delta.reasoning_content or ""

                            if "\n" in reasoning_token:
                                # 换行符添加 '> '
                                reasoning_token = reasoning_token.replace("\n", "\n> ")
                            if is_preprocess_token:
                                reasoning_token = self._preprocess_token(
                                    reasoning_token, tmp_cache
                                )
                            if reasoning_token:
                                yield {"token": reasoning_token, "type": "reasoning"}
                        if hasattr(delta, "content"):
                            token = delta.content or ""
                            if is_preprocess_token:
                                token = self._preprocess_token(token, tmp_cache)
                            if token:
                                yield {"token": token, "type": "content"}
                return
            except self.retryable_errors as e:
                last_error = e
                wait_time = self.retry_delay * (2**attempt)
                self.logger.warning(
                    f"Async attempt {attempt + 1}/{self.max_retries} failed. Retrying in {wait_time}s. Error: {e}"
                )
                await asyncio.sleep(wait_time)
            except Exception as e:
                self.logger.error(f"Non-retryable error in aquery: {e}")
                raise
        raise (
            last_error
            if last_error
            else Exception("Unknown error in aquery after max retries")
        )

    def get_embeddings(
        self,
        texts: Union[str, List[str]],
        model_name: str = "qwen-1.5b",
        deployment: str = "embedding",
    ) -> List[List[float]]:
        # ... (和之前版本完全一样，无需改动)
        api_config = self._get_api_config(deployment)
        embed_client = self._get_embedding_client(
            api_config["api_base"], api_config["api_key"]
        )
        return embed_client.embed(texts, model_name)

    async def aget_embeddings(
        self,
        texts: Union[str, List[str]],
        model_name: str = "qwen-1.5b",
        deployment: str = "embedding",
    ) -> List[List[float]]:
        # ... (和之前版本完全一样，无需改动)
        api_config = self._get_api_config(deployment)
        embed_client = self._get_embedding_client(
            api_config["api_base"], api_config["api_key"]
        )
        return await embed_client.aembed(texts, model_name)

    # --- 工具方法 ---
    ### MODIFIED ###
    def _get_api_config(self, deployment: str) -> Dict[str, str]:
        settings = get_settings()
        configs = {
            "ali": {
                "api_key": settings.llm_api_key,
                "api_base": settings.llm_api_base_url,
            },
        }
        if deployment not in configs:
            raise ValueError(
                f"Unknown deployment type: {deployment}. Available: {list(configs.keys())}"
            )
        return configs[deployment]

    def compute_similarity(
        self, embedding1: List[float], embedding2: List[float]
    ) -> float:
        # ... (和之前版本完全一样，无需改动)
        v1 = np.array(embedding1)
        v2 = np.array(embedding2)
        dot_product = np.dot(v1, v2)
        norm_v1 = np.linalg.norm(v1)
        norm_v2 = np.linalg.norm(v2)
        if norm_v1 == 0 or norm_v2 == 0:
            return 0.0
        return float(dot_product / (norm_v1 * norm_v2))

    def clear_cache(self) -> None:
        # ... (和之前版本完全一样，无需改动)
        self._sync_client_cache.clear()
        self._async_client_cache.clear()
        self._embedding_client_cache.clear()
        self.logger.info("All client caches have been cleared.")


class OpenAIEmbeddingsClient:
    # ... (和之前版本完全一样，无需改动)
    """一个简单的 Embedding 客户端，封装了同步和异步 OpenAI 客户端。"""

    def __init__(self, api_base: str, api_key: str):
        self.sync_client = OpenAI(
            api_key=api_key, base_url=api_base, timeout=30, max_retries=2
        )
        self.async_client = AsyncOpenAI(
            api_key=api_key, base_url=api_base, timeout=30, max_retries=2
        )

    def embed(self, texts: Union[str, List[str]], model: str) -> List[List[float]]:
        if isinstance(texts, str):
            texts = [texts]
        response = self.sync_client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]

    async def aembed(
        self, texts: Union[str, List[str]], model: str
    ) -> List[List[float]]:
        if isinstance(texts, str):
            texts = [texts]
        response = await self.async_client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]


# --- 使用示例 ---


# 定义用于 vLLM JSON Schema 的 Pydantic 模型
class UserInfo(BaseModel):
    """用于提取用户信息的结构化数据"""

    name: str
    age: int
    email: str
    hobbies: List[str]


async def main():
    llm_client = LLMClient()

    # === 1. 测试 vLLM 的 JSON Schema 强制输出功能 (deployment='local') ===
    print("=== 1. 测试 vLLM 的 JSON Schema 功能 ===")
    # 假设您的 vLLM 服务在 http://127.0.0.1:7555/v1 运行
    try:
        # system_message 不是必须的，但提供指导有助于模型更好地填充 schema
        system_msg_vllm = f"You are an expert data extraction bot. Extract user information based on the provided Pydantic JSON schema."

        vllm_json_response = await llm_client.aquery(
            query="我的名字是王五，今年34岁，邮箱是wangwu@example.com，爱好是打篮球和旅游。",
            model_name="qwen3-a3b",  # 替换为您 vLLM 部署的模型名
            deployment="local",
            system_message=system_msg_vllm,
            json_mode=UserInfo,  # <<< 关键：直接传入 Pydantic 模型类
        )
        print(f"vLLM JSON Schema 输出:\n{vllm_json_response}")
        # 验证输出
        try:
            parsed_data = UserInfo.model_validate_json(vllm_json_response)
            print(f"vLLM JSON Schema 解析成功: {parsed_data.model_dump_json(indent=2)}")
        except Exception as e:
            print(f"vLLM JSON Schema 解析失败: {e}")

    except Exception as e:
        print(
            f"vLLM JSON Schema 测试出错 (请确保 vLLM 服务已在 http://127.0.0.1:7555/v1 运行): {e}"
        )

    # === 2. 测试 Qwen 的 JSON Mode 功能 (deployment='ali') ===
    print("\n=== 2. 测试 Qwen 的 JSON Mode 功能 ===")
    try:
        # Qwen 需要在 prompt 中包含 'json' 关键字
        system_msg_qwen = (
            "请从以下文本中提取姓名、年龄、邮箱和爱好，并以JSON对象格式返回。"
        )

        qwen_json_response = await llm_client.aquery(
            query="大家好，我叫张三，今年25岁，邮箱是zhangsan@example.com，平时喜欢唱歌。",
            model_name="qwen-plus",
            deployment="ali",
            system_message=system_msg_qwen,
            json_mode=True,  # <<< 关键：使用布尔值 True
            enable_thinking=True,  # 这会被自动禁用并打印警告
        )
        print(f"Qwen JSON Mode 输出:\n{qwen_json_response}")
        # 验证输出
        try:
            parsed_json = json.loads(qwen_json_response)
            print(
                f"Qwen JSON 解析成功: {json.dumps(parsed_json, indent=2, ensure_ascii=False)}"
            )
        except json.JSONDecodeError as e:
            print(f"Qwen JSON 解析失败: {e}")
    except Exception as e:
        print(f"Qwen JSON Mode 测试出错: {e}")

    # === 3. 测试普通异步查询 (兼容性检查) ===
    print("\n=== 3. 测试普通异步查询 ===")
    try:
        normal_response = await llm_client.aquery(
            "你好，请用一句话介绍一下异步编程的优势。",
            model_name="qwen-plus",
            deployment="ali",
        )
        print(f"普通模式回复: {normal_response}")
    except Exception as e:
        print(f"普通查询出错: {e}")

    # === 4. 测试 Embedding 功能 (兼容性检查) ===
    print("\n=== 4. 测试 Embedding 功能 ===")
    # 假设您的 Embedding 服务在 http://127.0.0.1:7900/v1 运行
    try:
        embeddings = await llm_client.aget_embeddings(
            ["你好", "世界"],
            model_name="bge-m3",  # 替换为您的 embedding 模型名
            deployment="embedding",
        )
        print(
            f"获取到 {len(embeddings)} 个 Embeddings. 第一个向量维度: {len(embeddings[0])}"
        )
    except Exception as e:
        print(
            f"Embedding 测试出错 (请确保 Embedding 服务在 http://127.0.0.1:7900/v1 运行): {e}"
        )

        ### NEW TEST CASE for Vision Model ###
    print("\n=== 新增：测试本地视觉模型 (local_vl) ===")
    try:
        # 您可以使用一个网络图片的URL，或者一个本地文件的路径
        # 例如: image_path = "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Cat_August_2010-4.jpg/1200px-Cat_August_2010-4.jpg"
        # 或者: image_path = "/path/to/your/local/image.jpg"
        image_path = "http://192.168.0.156:9000/research-report-charts/25615380/Figure_Page-3_Count-1.png"  # 使用一个网络图片作为示例
        oss_name = encode_upload_name_from_url(image_path)
        image_path = (
            f"https://ly-data-report-charts.oss-cn-shenzhen.aliyuncs.com/{oss_name}"
        )

        vision_response = await llm_client.aquery(
            query="这张图片里有什么？请用中文回答。",
            model_name="qwen25-vl-7b",  # 使用您提供的视觉模型ID
            deployment="local_vl",  # 使用新的部署配置
            image_url=image_path,  # 传入图片URL
        )
        print(f"本地视觉模型回复: {vision_response}")
    except Exception as e:
        print(
            f"本地视觉模型测试出错 (请确保 vLLM-VL 服务已在 http://127.0.0.1:7555/vl/v1 运行): {e}"
        )


import hashlib
from urllib.parse import urlparse


def encode_upload_name_from_url(object_url) -> str:
    """
    从URL中提取文件名，并进行哈希编码。
    """
    try:
        parsed_url = urlparse(object_url)
        path_parts = parsed_url.path.strip("/").split("/")

        if len(path_parts) < 2:
            raise Exception(
                "Invalid path format for upload, path should contain at least two parts"
            )

        # bucket_name = path_parts[0]  # MinIO的桶名
        object_name = "/".join(path_parts[1:])  # MinIO的对象名

        # 获取文件扩展名
        file_ext = ""
        if "." in object_name:
            file_ext = object_name.split(".")[-1].lower()

        # 生成哈希文件名
        hashed_name = hashlib.sha256(object_name.encode("utf-8")).hexdigest()

        # 针对PNG图片，转换为JPG
        if file_ext == "png":
            file_ext = "jpg"  # 压缩后保存为jpg

        aliyun_object = f"{hashed_name}.{file_ext}"
        return aliyun_object
    except Exception as e:
        print(f"Error: {str(e)}")
        raise Exception("Invalid path format for upload")


if __name__ == "__main__":
    asyncio.run(main())
