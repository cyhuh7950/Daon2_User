"use client";

import {
  cancelStudioOutput, createStudioMemo, createMemoSource, reflectMemoSource, createStudioOutput, applyStudioEditTurn, createStudioEditTurn, discardStudioEditTurn, listStudioEditTurns, createStudioRevision, deleteStudioOutput, downloadStudioExport, getStudioAudio, getStudioVideo, getStudioEvidenceContent,
  getStudioOutput, getStudioProvenance, getStudioSharing, listLearningAttempts, listStudioOutputs, listStudioTypes, recordLearningAttempt,
  regenerateStudioOutput, renameStudioOutput, getStudioCustomization, saveStudioCustomization,
  copyNotebook, clearChatHistory, listChatTurns, getModelSelection, saveModelSelection, getQuestionTools, saveQuestionTools, getNotebookOverview, regenerateNotebookOverview,
  listSourceGroups, createSourceGroup, updateSourceGroup, deleteSourceGroup, setSourceGroupMembers, searchSourceDiscovery, addSourceDiscovery, issueExportStepUp,
  listAuthoringTemplates, createAuthoringSession, getAuthoringSession, answerAuthoringSession, reviewAuthoringSession, controlAuthoringSession, editAuthoringUnit, updateAuthoringOutline, listKnowledgeConnectors, listConnectorDocuments,
} from "./studio-v2-api.js";
import { localMemoTitle } from "./memo-title.js";

// 노트북 범위(workspaceId, notebookId)를 미리 묶은 Studio v2 어댑터. 셸·패널은 이 객체만 쓴다.
export function createStudioV2Adapter(workspaceId, notebookId, { fetchImpl } = {}) {
  if (!workspaceId || !notebookId) return undefined;
  const scope = (options = {}) => ({ ...options, notebookId, fetchImpl });
  let exportFormatsByType = new Map();
  return Object.freeze({
    enabled: true,
    listTypes: async (options) => {
      const types = await listStudioTypes(workspaceId, scope(options));
      exportFormatsByType = new Map(types.map((t) => [t.type_id, t.export_formats]));
      return types;
    },
    exportFormats: (typeId) => exportFormatsByType.get(typeId) ?? [],
    listOutputs: (options) => listStudioOutputs(workspaceId, scope(options)),
    getOutput: (outputId, options) => getStudioOutput(workspaceId, outputId, scope(options)),
    createOutput: (input) => createStudioOutput(workspaceId, scope(input)),
    renameOutput: (outputId, title, options) => renameStudioOutput(workspaceId, outputId, title, scope(options)),
    deleteOutput: (outputId, options) => deleteStudioOutput(workspaceId, outputId, scope(options)),
    cancelOutput: (outputId, options) => cancelStudioOutput(workspaceId, outputId, scope(options)),
    regenerateOutput: (outputId, options) => regenerateStudioOutput(workspaceId, outputId, scope(options)),
    createRevision: (outputId, input) => createStudioRevision(workspaceId, outputId, scope(input)),
    createEditTurn: (outputId, input) => createStudioEditTurn(workspaceId, outputId, scope(input)),
    listEditTurns: (outputId, options) => listStudioEditTurns(workspaceId, outputId, scope(options)),
    applyEditTurn: (outputId, turnId, options) => applyStudioEditTurn(workspaceId, outputId, turnId, scope(options)),
    discardEditTurn: (outputId, turnId, options) => discardStudioEditTurn(workspaceId, outputId, turnId, scope(options)),
    getProvenance: (outputId, options) => getStudioProvenance(workspaceId, outputId, scope(options)),
    downloadExport: (outputId, format, options) => downloadStudioExport(workspaceId, outputId, format, scope(options)),
    getAudio: (outputId, options) => getStudioAudio(workspaceId, outputId, scope(options)),
    getVideo: (outputId, options) => getStudioVideo(workspaceId, outputId, scope(options)),
    getEvidenceContent: (outputId, refId, options) => getStudioEvidenceContent(workspaceId, outputId, refId, scope(options)),
    getSharing: (outputId, options) => getStudioSharing(workspaceId, outputId, scope(options)),
    recordLearningAttempt: (outputId, input) => recordLearningAttempt(workspaceId, outputId, scope(input)),
    listLearningAttempts: (outputId, options) => listLearningAttempts(workspaceId, outputId, scope(options)),
    createMemo: (input) => createStudioMemo(workspaceId, scope({ ...input, title: input?.title ?? localMemoTitle() })),
    // 메모를 소스로(WO-N1 NB1-F2): 응답 {source_id, source_version_id, state} / 반영 {source_id, source_version_id}.
    createMemoSource: (outputId, options) => createMemoSource(workspaceId, outputId, scope(options)),
    reflectMemoSource: (outputId, options) => reflectMemoSource(workspaceId, outputId, scope(options)),
    issueExportStepUp: (outputId, password, options) => issueExportStepUp(outputId, password, options),
    copyNotebook: (input) => copyNotebook(workspaceId, scope(input)),
    clearChatHistory: (options) => clearChatHistory(workspaceId, scope(options)),
    listChatTurns: (options) => listChatTurns(workspaceId, scope(options)),
    getModelSelection: (options) => getModelSelection(workspaceId, scope(options)),
    saveModelSelection: (options) => saveModelSelection(workspaceId, scope(options)),
    getQuestionTools: (options) => getQuestionTools(workspaceId, scope(options)),
    saveQuestionTools: (enabled, options) => saveQuestionTools(workspaceId, scope({ ...options, enabled })),
    // 노트북 개요·추천 질문(WO-N1 NB2-F2): 조회는 보기, 다시 만들기는 편집 권한. queued·working이면 3초 간격 폴링.
    getNotebookOverview: (options) => getNotebookOverview(workspaceId, scope(options)),
    regenerateNotebookOverview: (options) => regenerateNotebookOverview(workspaceId, scope(options)),
    // 소스 묶음(WO-N1 NB3-F2): 조회는 보기, 변경은 편집 권한. 변경은 마지막 ETag(options.etag)를 보낸다.
    listSourceGroups: (options) => listSourceGroups(workspaceId, scope(options)),
    createSourceGroup: (name, options) => createSourceGroup(workspaceId, scope({ ...options, name })),
    updateSourceGroup: (groupId, options) => updateSourceGroup(workspaceId, groupId, scope(options)),
    deleteSourceGroup: (groupId, options) => deleteSourceGroup(workspaceId, groupId, scope(options)),
    setSourceGroupMembers: (groupId, sourceIds, options) => setSourceGroupMembers(workspaceId, groupId, scope({ ...options, sourceIds })),
    // 자료 찾기·빠른 찾기(WO-N1 NB4-F1): 검색은 보기, 추가는 편집 권한. 추가는 사람이 고른 ref 하나씩(자동 추가 없음).
    searchSourceDiscovery: (query, scopes, options) => searchSourceDiscovery(workspaceId, scope({ ...options, query, scopes })),
    addSourceDiscovery: (ref, options) => addSourceDiscovery(workspaceId, scope({ ...options, ref })),
    getCustomization: (options) => getStudioCustomization(workspaceId, scope(options)),
    saveCustomization: (instruction, options) => saveStudioCustomization(workspaceId, instruction, scope(options)),
    authoring: Object.freeze({
      listTemplates: (options) => listAuthoringTemplates(workspaceId, scope(options)),
      createSession: (input) => createAuthoringSession(workspaceId, scope(input)),
      getSession: (outputId, options) => getAuthoringSession(workspaceId, outputId, scope(options)),
      answer: (outputId, input) => answerAuthoringSession(workspaceId, outputId, scope(input)),
      review: (outputId, input) => reviewAuthoringSession(workspaceId, outputId, scope(input)),
      control: (outputId, input) => controlAuthoringSession(workspaceId, outputId, scope(input)),
      editUnit: (outputId, unitKey, input) => editAuthoringUnit(workspaceId, outputId, unitKey, scope(input)),
      outline: (outputId, input) => updateAuthoringOutline(workspaceId, outputId, scope(input)),
      listConnectors: (options) => listKnowledgeConnectors({ ...options, fetchImpl }),
      listDocuments: (connectorId, options) => listConnectorDocuments(connectorId, { ...options, fetchImpl }),
    }),
  });
}
