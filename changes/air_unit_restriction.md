# 修改：3 倍于基础收入前不允许制造空中单位

修改思路：
原 `h06C` 代码对应农场，将农场描述进行修改并将所有空中单位前置依赖加上该代码。
在获取到三倍于基础收入时，利用 `SetPlayerTechResearched` 添加农场，从而允许制造空中单位。

具体修改位置：

逆向后的 `AdjustIncomeOnBuilt`() 负责在建筑建造完成后进行收入调整，此时可加入回调负责查看是否允许空中单位。

变量对应关系见 [变量对应文档](../re/variables.md)。

涉及到的文件:

- `manual_translate_out/humanunitfunc.txt`：添加了对 `h06C` 的依赖
- `manual_translate_out/campaignunitfunc.txt`：添加了对 `h06C` 的依赖
- `manual_translate_out/humanunitstrings.txt`：修改了农场的介绍（“拱” 修改为 “获得3 倍初始收入前不允许制造空中单位”）
- `manual_translate_out/war3map.j`：修改脚本，加入 3 倍收入的判断逻辑。脚本修改处见 `// modification` 注释