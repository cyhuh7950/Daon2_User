"use client";

import {
  cancelStudioOutput, createStudioMemo, createStudioOutput, createStudioRevision, deleteStudioOutput, downloadStudioExport, getStudioAudio, getStudioVideo, getStudioEvidenceContent,
  getStudioOutput, getStudioProvenance, getStudioSharing, listLearningAttempts, listStudioOutputs, listStudioTypes, recordLearningAttempt,
  regenerateStudioOutput, renameStudioOutput, getStudioCustomization, saveStudioCustomization,
  copyNotebook, clearChatHistory, listChatTurns, getModelSelection, saveModelSelection, issueExportStepUp,
  listAuthoringTemplates, createAuthoringSession, getAuthoringSession, answerAuthoringSession, reviewAuthoringSession, listKnowledgeConnectors, listConnectorDocuments,
} from "./studio-v2-api.js";

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
    getProvenance: (outputId, options) => getStudioProvenance(workspaceId, outputId, scope(options)),
    downloadExport: (outputId, format, options) => downloadStudioExport(workspaceId, outputId, format, scope(options)),
    getAudio: (outputId, options) => getStudioAudio(workspaceId, outputId, scope(options)),
    getVideo: (outputId, options) => getStudioVideo(workspaceId, outputId, scope(options)),
    getEvidenceContent: (outputId, refId, options) => getStudioEvidenceContent(workspaceId, outputId, refId, scope(options)),
    getSharing: (outputId, options) => getStudioSharing(workspaceId, outputId, scope(options)),
    recordLearningAttempt: (outputId, input) => recordLearningAttempt(workspaceId, outputId, scope(input)),
    listLearningAttempts: (outputId, options) => listLearningAttempts(workspaceId, outputId, scope(options)),
    createMemo: (input) => createStudioMemo(workspaceId, scope(input)),
    issueExportStepUp: (outputId, password, options) => issueExportStepUp(outputId, password, options),
    copyNotebook: (input) => copyNotebook(workspaceId, scope(input)),
    clearChatHistory: (options) => clearChatHistory(workspaceId, scope(options)),
    listChatTurns: (options) => listChatTurns(workspaceId, scope(options)),
    getModelSelection: (options) => getModelSelection(workspaceId, scope(options)),
    saveModelSelection: (options) => saveModelSelection(workspaceId, scope(options)),
    getCustomization: (options) => getStudioCustomization(workspaceId, scope(options)),
    saveCustomization: (instruction, options) => saveStudioCustomization(workspaceId, instruction, scope(options)),
    authoring: Object.freeze({
      listTemplates: (options) => listAuthoringTemplates(workspaceId, scope(options)),
      createSession: (input) => createAuthoringSession(workspaceId, scope(input)),
      getSession: (outputId, options) => getAuthoringSession(workspaceId, outputId, scope(options)),
      answer: (outputId, input) => answerAuthoringSession(workspaceId, outputId, scope(input)),
      review: (outputId, input) => reviewAuthoringSession(workspaceId, outputId, scope(input)),
      listConnectors: (options) => listKnowledgeConnectors({ ...options, fetchImpl }),
      listDocuments: (connectorId, options) => listConnectorDocuments(connectorId, { ...options, fetchImpl }),
    }),
  });
}
