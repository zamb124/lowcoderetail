(function() {
  // 'apiInternal' будет ссылкой на внутреннее API HTMX для расширений,
  // а 'htmxGlobal' будет ссылкой на глобальный объект htmx.
  let apiInternal;
  const htmxGlobal = window.htmx; // Получаем доступ к глобальному htmx

  if (!htmxGlobal) {
    console.error("HTMX global object not found. json-enc extension cannot be initialized.");
    return;
  }

  htmxGlobal.defineExtension('json-enc', {
    init: function(apiRef) {
      apiInternal = apiRef; // Сохраняем ссылку на внутреннее API HTMX
    },

    onEvent: function(name, evt) {
      if (name === 'htmx:configRequest') {
        evt.detail.headers['Content-Type'] = 'application/json';
      }
    },

    encodeParameters: function(xhr, parameters, elt) {
      xhr.overrideMimeType('text/json');

      const object = {};
      // Используем apiInternal для getExpressionVars, так как это метод внутреннего API расширений
      const hxValues = apiInternal.getExpressionVars(elt);

      // 1. Применяем значения из hx-vals и hx-vars
      for (const key in hxValues) {
        if (Object.hasOwn(hxValues, key)) {
          if (Object.hasOwn(object, key)) {
            if (!Array.isArray(object[key])) {
              object[key] = [object[key]];
            }
            object[key].push(hxValues[key]);
          } else {
            object[key] = hxValues[key];
          }
        }
      }

      // 2. Определяем, есть ли форма
      let formElement = null;
      if (elt.tagName === 'FORM') {
        formElement = elt;
      } else if (elt.form) {
        formElement = elt.form;
      } else {
        // Используем htmxGlobal.closest для поиска формы
        formElement = htmxGlobal.closest(elt, 'form'); // <--- ИСПРАВЛЕНИЕ
      }

      if (formElement) {
        // 2a. Если есть форма, проходим по ее элементам
        for (let i = 0; i < formElement.elements.length; i++) {
          const input = formElement.elements[i];

          if (!input.name || input.disabled || input.type === 'submit' || input.type === 'button' || input.type === 'reset' || input.type === 'file') {
            continue;
          }

          if (Object.hasOwn(hxValues, input.name)) {
            continue;
          }

          let value;
          if (input.type === 'checkbox') {
            value = input.checked;
          } else if (input.type === 'radio') {
            if (input.checked) {
              value = input.value;
            } else {
              continue;
            }
          } else if (input.tagName === 'SELECT' && input.multiple) {
            value = [];
            for (let j = 0; j < input.options.length; j++) {
              if (input.options[j].selected) {
                value.push(input.options[j].value);
              }
            }
          } else {
            if (parameters.has(input.name)) {
              const formValues = parameters.getAll(input.name);
              value = formValues.length > 1 ? formValues : formValues[0];
            } else {
              continue;
            }
          }

          if (Object.hasOwn(object, input.name)) {
            if (!Array.isArray(object[input.name])) {
              object[input.name] = [object[input.name]];
            }
            object[input.name].push(value);
          } else {
            object[input.name] = value;
          }
        }
      } else {
        // 2b. Если нет формы
        if (elt.name && !Object.hasOwn(hxValues, elt.name)) {
          if (elt.type === 'checkbox') {
            object[elt.name] = elt.checked;
          } else if (elt.type === 'radio' && elt.checked) {
            object[elt.name] = elt.value;
          }
          // Для других типов элементов без формы, если они имеют name и value,
          // и не переопределены в hx-vals, можно добавить их значение.
          // Но это может быть избыточно, если они не должны отправляться.
          // Исходная логика parameters.forEach ниже покроет hx-params.
        }

        parameters.forEach(function(paramValue, paramKey) {
          if (Object.hasOwn(object, paramKey) && Object.hasOwn(hxValues, paramKey) ) {
             // Если ключ уже есть в object И он пришел из hxValues, то не перезаписываем из parameters
             // Это нужно, чтобы hx-vals имел приоритет над hx-params для того же ключа.
             return;
          }
          if (Object.hasOwn(object, paramKey) && !Object.hasOwn(hxValues, paramKey) && elt.name === paramKey) {
             // Если ключ уже есть в object (например, от самого elt), и это не из hxValues,
             // и это имя самого elt, то не перезаписываем из parameters (hx-params).
             // Это предотвращает дублирование, если elt.name совпадает с ключом в hx-params.
             return;
          }


          const typedValue = Object.hasOwn(hxValues, paramKey) ? hxValues[paramKey] : paramValue;

          if (Object.hasOwn(object, paramKey)) {
            if (!Array.isArray(object[paramKey])) {
              object[paramKey] = [object[paramKey]];
            }
            object[paramKey].push(typedValue);
          } else {
            object[paramKey] = typedValue;
          }
        });
      }

      return JSON.stringify(object);
    }
  });
})();