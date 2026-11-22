# 发布页 DOM 结构与解析规则

实测时间：2026-11-06，小红书创作服务平台（creator.xiaohongshu.com）。

## 编辑器

- 编辑器根节点：`.ProseMirror`（tiptap / ProseMirror）
- **必须先有图片才渲染**：视频 tab 下没有正文编辑器；切到「上传图文」并成功上传 1 张图后，`.ProseMirror` 才出现
- 上传入口：`input.upload-input`（隐藏的 file input），用 CDP `DOM.setFileInputFiles` 注入，不需要点击
- 占位图会在草稿箱留一条**浏览器本地**草稿，不进账号

## 话题下拉

结构：

```
<div class="items">          <- 可滚动容器
  <div class="item">#话题名</div>
  <div class="item">12.3亿浏览</div>   <- 实际每行是一个 .item 内含两行文本
</div>
```

解析规则：

- 每一行 `el.innerText` 用换行切分，`#` 开头的行取话题名，`/浏览$/` 结尾的行取浏览量
- 浏览量文本 → 数值：`12.3亿` → 1230000000，`3908.5万` → 39085000
- **每词上限 50 条**：滚到底后 `scrollTop === scrollHeight - clientHeight`，无「加载更多」节点。实测 8 轮滚动无新增，确认是平台硬上限

## 输入方式

- 逐字 `Input.insertText` 输入 `#关键词`，每字间隔 60~130ms（一次性 insertText 会不触发联想）
- 输入后等待约 1300ms 让下拉渲染，再开始「读取 → 滚动 → 读取」循环
- 连续 3 轮无新增视为到底

## 清空

全选编辑器内容（Range + Selection）后派发 `Input.dispatchKeyEvent` 的 `Delete`（keyDown + keyUp），等待 350ms。

## 页面结构可能变化时的排查顺序

1. `document.querySelectorAll('.items .item').length` 是否为 0
2. 手动输入 `#测试` 后，查找页面上 `/浏览$/` 的裸文本节点，向上回溯 1~6 层找到「话题名 + 浏览量」同容器的最小父节点
3. 用该父节点的 class 替换 `HARVEST` 里的选择器
4. 校验条数是否仍为 50 上封顶

## 风控信号

页面正文出现 `滑动验证` / `拖动滑块` / `安全验证` / `请完成验证` / `操作过于频繁` / `账号异常` 时立即停止。
