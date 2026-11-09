"""내장 작성 템플릿 `general_document`. 맞는 템플릿이 없을 때 쓰며, 목차는 LLM이 만든다(WO-K4 K-4)."""

TEMPLATE = {'template_id': 'general_document',
 'title': '일반 문서',
 'version': 1,
 'description': '요청에 맞춰 LLM이 목차를 만들고 선택한 지식을 근거로 작성한다.',
 'keywords': [],
 'analysis': 'free_outline',
 'inputs': [{'key': 'document_goal', 'question': '어떤 문서를 무슨 목적으로 작성할까요?', 'kind': 'text', 'required': True}],
 'knowledge': [],
 'sections': [{'key': 'body', 'title': '본문', 'guidance': '요청에 맞게 작성한다.'}],
 'checks': [],
 'output': {'formats': ['docx', 'pptx'], 'default': ['docx']}}
